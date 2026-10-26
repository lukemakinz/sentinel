"""Frozen, retrospective S15 4h time-series momentum experiment."""
import argparse
from dataclasses import replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.time_series_momentum import (
    TSM4HConfig,
    build_tsm_features,
    generate_tsm_events,
)
from .swing_data import BASE_URL, load_interval_archives, regularize_interval
from .swing_portfolio import SwingExecutionConfig, execute_swing_portfolio


REFERENCE = 'BTCUSDT'
TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
ALL_SYMBOLS = (REFERENCE, *TRADED)
WARMUP, END = '2021-01-01', '2026-09-01'
WINDOWS = {
    'development': ('2021-04-01', '2024-01-01'),
    'validation': ('2024-01-01', '2025-01-01'),
    'retrospective_evaluation': ('2025-01-01', END),
}
POLICIES = (
    'initial_sl_only',
    'delayed_cost_be',
    'delayed_cost_be_chandelier',
)


def _numeric_pf(summary):
    value = summary['profit_factor']
    if value == 'Infinity':
        return float('inf')
    return float(value or 0.0)


def _development_pass(summary):
    return (summary['trades'] >= 30 and summary['net_pnl'] > 0
            and _numeric_pf(summary) > 1.05)


def _validation_pass(base, stress):
    return (base['trades'] >= 10 and base['net_pnl'] > 0
            and _numeric_pf(base) > 1.10 and _numeric_pf(stress) >= 1.00
            and base['represented_symbols'] >= 2)


def _execution(policy, scenario):
    config = SwingExecutionConfig(exit_policy=policy)
    if scenario == 'stress':
        return replace(config, fee_bps=8.0, slippage_bps=5.0)
    if scenario == 'severe':
        return replace(config, fee_bps=10.0, slippage_bps=10.0)
    return config


def _required_archives():
    months = pd.period_range(
        WARMUP, pd.Timestamp(END) - pd.Timedelta(minutes=5), freq='M')
    records = []
    for symbol in ALL_SYMBOLS:
        for month in months:
            for relative in (
                f'klines/{symbol}/5m/{symbol}-5m-{month}.zip',
                f'fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip',
            ):
                records.append({
                    'relative_path': relative,
                    'url': f'{BASE_URL}/{relative}',
                    'checksum_url': f'{BASE_URL}/{relative}.CHECKSUM',
                })
    return records


def _run_window(data, entries, exits, management, policy, scenario, start, end):
    return execute_swing_portfolio(
        {symbol: data[symbol] for symbol in TRADED},
        entries, exits, management, _execution(policy, scenario),
        start, end, initial_capital=250.0, symbol_priority=TRADED,
    )


def _report(results, protocol_hash):
    lines = [
        '# S15 — 4h time-series momentum / Donchian',
        '',
        f'Hash zamrożonego protokołu: `{protocol_hash}`.',
        '',
        'To test retrospektywny, nie obietnica zysku ani zgoda na handel live. '
        'Każda polityka wyjścia przechodzi bramki samodzielnie.',
        '',
        '| Prowadzenie pozycji | Okno | Koszty | Transakcje | WR | PF | PnL | Zwrot | Max DD |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for policy, record in results.items():
        for window, scenarios in record['windows'].items():
            for scenario, summary in scenarios.items():
                pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
                lines.append(
                    f'| {policy} | {window} | {scenario} | {summary["trades"]} | '
                    f'{summary["win_rate_pct"]:.1f}% | {pf} | ${summary["net_pnl"]:.2f} | '
                    f'{summary["return_pct"]:.3f}% | {summary["max_drawdown_pct"]:.3f}% |'
                )
        lines.extend(['', f'- Decyzja `{policy}`: **{record["decision"]}**.', ''])
    lines.extend([
        '## Wykonanie i ryzyko',
        '',
        'Kapitał $250; jeden wspólny portfel ETH/SOL/BNB; ryzyko do $0,50 na '
        'transakcję; notional do 50% equity; margin do 10% equity; dźwignia do 5x. '
        'Wszystkie wejścia i wyjścia są market, finansowanie historyczne jest rozliczone.',
        '',
        'Cost-BE i Chandelier powstają wyłącznie po zamknięciu pełnej świecy 4h i '
        'działają od następnej świecy 5m. W niejednoznacznej świecy stary stop ma '
        'pierwszeństwo.',
    ])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-swing-cache')
    parser.add_argument('--output', default='docs/research/s15_tsm_4h')
    args = parser.parse_args()
    output, cache = Path(args.output), Path(args.cache)
    output.mkdir(parents=True, exist_ok=True)

    protocol = output / 'protocol.json'
    recorded_hash = (output / 'protocol.sha256').read_text().split()[0]
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != recorded_hash:
        raise ValueError('Frozen protocol hash mismatch; refusing to load market data')
    required = _required_archives()
    (output / 'required_archives.json').write_text(json.dumps({
        'count': len(required), 'files': required,
    }, indent=2) + '\n')

    data, manifest, data_quality = {}, {}, {}
    for symbol in ALL_SYMBOLS:
        candles, funding, manifest[symbol] = load_interval_archives(
            symbol, WARMUP, END, str(cache), interval='5m', allow_gaps=True)
        expected = pd.date_range(WARMUP, END, freq='5min', inclusive='left', tz='UTC')
        missing = expected.difference(candles.index)
        data_quality[symbol] = {
            'expected_5m_bars': len(expected),
            'observed_5m_bars': len(candles),
            'mtm_only_carried_bars': len(missing),
            'first_missing_bars': [str(timestamp) for timestamp in missing[:20]],
            'policy': ('prior real close for portfolio clock only; no entry, exit, '
                       'stop, time-stop or signal aggregation on synthetic rows'),
        }
        candles = regularize_interval(candles, WARMUP, END, minutes=5)
        data[symbol] = candles, funding
        print(symbol, 'verified 5m/funding archives ready;', len(missing),
              'MTM-only carried rows', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'data_quality.json').write_text(
        json.dumps(data_quality, indent=2) + '\n')

    strategy = TSM4HConfig()
    features = {
        symbol: build_tsm_features(data[symbol][0], strategy)
        for symbol in ALL_SYMBOLS
    }
    entries, exits = {}, {}
    for symbol in TRADED:
        entries[symbol], exits[symbol] = generate_tsm_events(
            features[symbol], features[REFERENCE]['daily'], symbol, strategy)
    management = {symbol: features[symbol]['four_hour'] for symbol in TRADED}

    results = {}
    for policy in POLICIES:
        record = {
            'entry_config': strategy.__dict__,
            'exit_policy': policy,
            'raw_entry_candidates': {
                window: sum(
                    pd.Timestamp(start, tz='UTC') <= event['timestamp']
                    < pd.Timestamp(end, tz='UTC')
                    for events in entries.values() for event in events
                )
                for window, (start, end) in WINDOWS.items()
            },
            'windows': {'development': {}},
        }
        for scenario in ('base', 'stress', 'severe'):
            result = _run_window(
                data, entries, exits, management, policy, scenario,
                *WINDOWS['development'])
            record['windows']['development'][scenario] = result['summary']
            payload = json.dumps(result['trades'], allow_nan=False).encode()
            (output / f'{policy}_development_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
            print(policy, 'development', scenario, result['summary']['trades'],
                  result['summary']['profit_factor'],
                  f'${result["summary"]["net_pnl"]:.2f}', flush=True)

        if not _development_pass(record['windows']['development']['base']):
            record['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
            results[policy] = record
            continue

        record['windows']['validation'] = {}
        for scenario in ('base', 'stress', 'severe'):
            result = _run_window(
                data, entries, exits, management, policy, scenario,
                *WINDOWS['validation'])
            record['windows']['validation'][scenario] = result['summary']
            payload = json.dumps(result['trades'], allow_nan=False).encode()
            (output / f'{policy}_validation_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
        validation = record['windows']['validation']
        if not _validation_pass(validation['base'], validation['stress']):
            record['decision'] = 'REJECTED_AT_VALIDATION_GATE'
            results[policy] = record
            continue

        record['windows']['retrospective_evaluation'] = {}
        for scenario in ('base', 'stress', 'severe'):
            result = _run_window(
                data, entries, exits, management, policy, scenario,
                *WINDOWS['retrospective_evaluation'])
            record['windows']['retrospective_evaluation'][scenario] = result['summary']
            payload = json.dumps(result['trades'], allow_nan=False).encode()
            (output / f'{policy}_evaluation_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
        evaluation = record['windows']['retrospective_evaluation']
        if (evaluation['base']['net_pnl'] <= 0
                or evaluation['stress']['net_pnl'] <= 0):
            record['decision'] = 'REJECTED_BY_RETROSPECTIVE_DECAY'
        else:
            record['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
        results[policy] = record

    payload = {
        'protocol_sha256': actual_hash,
        'disclosure': 'retrospective diagnostic; no untouched holdout',
        'results': results,
    }
    (output / 'summary.json').write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_report(results, actual_hash))


if __name__ == '__main__':
    main()
