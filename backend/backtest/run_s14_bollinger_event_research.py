"""Offline gated replay of S14 BB + PA/ICT/OB shadow-candidate queues."""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.bollinger_event_scalp import (
    bollinger_event_features,
    event_variants,
    generate_bollinger_event_signals,
)
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


REFERENCE = 'BTCUSDT'
TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
ALL_SYMBOLS = (REFERENCE, *TRADED)
WARMUP, END = '2025-07-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-08-01', '2026-02-01'),
    'validation': ('2026-02-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}


def _assert_offline_cache(cache: Path) -> None:
    months = pd.period_range(WARMUP, pd.Timestamp(END) - pd.Timedelta(minutes=1), freq='M')
    missing = []
    for symbol in ALL_SYMBOLS:
        for month in months:
            for path in (
                cache / 'klines' / symbol / '1m' / f'{symbol}-1m-{month}.zip',
                cache / 'fundingRate' / symbol / f'{symbol}-fundingRate-{month}.zip',
            ):
                if not path.exists() or not Path(f'{path}.CHECKSUM').exists():
                    missing.append(f'{symbol}:{month}:{path.parent.name}')
    if missing:
        raise FileNotFoundError(
            'Offline mode: required verified archives are absent; refusing network access: '
            + ', '.join(missing[:12]))


def _execution(config, scenario):
    base = config.execution()
    if scenario == 'stress':
        return replace(base, maker_fee_bps=5.0, fee_bps=8.0,
                       slippage_bps=5.0, limit_penetration_bps=5.0)
    if scenario == 'severe':
        return replace(base, maker_fee_bps=10.0, fee_bps=10.0,
                       slippage_bps=10.0, limit_penetration_bps=10.0)
    return base


def _pf(summary):
    if summary['profit_factor'] == 'Infinity':
        return float('inf')
    return float(summary['profit_factor'] or 0)


def _development_pass(summary):
    return summary['trades'] >= 30 and summary['net_pnl'] > 0 and _pf(summary) > 1.05


def _validation_pass(base, stress):
    share = base['largest_symbol_gross_profit_share_pct']
    return (
        base['trades'] >= 15 and base['net_pnl'] > 0 and _pf(base) > 1.10
        and stress['net_pnl'] > 0 and _pf(stress) >= 1.00
        and base['positive_symbols'] >= 2
        and share is not None and share <= 60
    )


def _run_window(data, raw, config, scenario, bounds):
    result = execute_cluster(
        {symbol: data[symbol] for symbol in TRADED}, raw,
        _execution(config, scenario), *bounds, initial_capital=250,
        symbol_priority=TRADED,
    )
    return result['summary'], result['trades']


def _candidate_counts(raw):
    return {
        name: sum(
            pd.Timestamp(start, tz='UTC') <= signal['timestamp'] < pd.Timestamp(end, tz='UTC')
            for rows in raw.values() for signal in rows
        )
        for name, (start, end) in WINDOWS.items()
    }


def _render_report(results, protocol_hash):
    lines = [
        '# S14 — BB + causal event PA/ICT/OB → kandydat shadow AI',
        '',
        f'Hash zamrożonego protokołu: `{protocol_hash}`.',
        '',
        'Wynik approve-all mierzy jakość mechanicznej kolejki, nie skuteczność AI. '
        'Historyczne miesiące były wcześniej oglądane i nie są nowym holdoutem.',
        '',
        '| Trasa | Okno | Koszty | Kandydaci | Fille | WR | PF | PnL | Zwrot | Max DD MTM |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for route, item in results.items():
        for window, scenarios in item['windows'].items():
            for scenario, summary in scenarios.items():
                pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
                lines.append(
                    f'| {route} | {window} | {scenario} | '
                    f'{item["raw_candidates_by_window"][window]} | {summary["trades"]} | '
                    f'{summary["win_rate_pct"]:.1f}% | {pf} | ${summary["net_pnl"]:.2f} | '
                    f'{summary["return_pct"]:.3f}% | {summary["max_drawdown_pct"]:.3f}% |'
                )
        lines.extend(['', f'- Decyzja `{route}`: **{item["decision"]}**.', ''])
    lines.extend([
        '## Zasady interpretacji',
        '',
        '- Wariant przegrywający development nie jest strojony ani otwierany na validation.',
        '- Stress/severe ponownie stosuje znany przed wejściem filtr 4× kosztu i większy '
        'trade-through; mniejsza liczba filli nie oznacza odporności.',
        '- Każdy zapisany sygnał zawiera twarde warunki, wektor 6 potwierdzeń, quorum, '
        '`setup_id` i stałą geometrię. AI może wyłącznie APPROVE/REJECT.',
        '- Nawet przejście wszystkich historycznych bramek oznaczałoby tylko paper-forward.',
        '',
    ])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s14_bollinger_event')
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before loading data')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')
    _assert_offline_cache(cache)

    data, manifest = {}, {}
    for symbol in ALL_SYMBOLS:
        minutes, funding, manifest[symbol] = load_archives(symbol, WARMUP, END, str(cache))
        data[symbol] = minutes, funding
        print(symbol, 'verified archives ready', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    features = {symbol: bollinger_event_features(data[symbol][0]) for symbol in ALL_SYMBOLS}

    results = {}
    for config in event_variants():
        raw = {
            symbol: generate_bollinger_event_signals(
                features[symbol], features[REFERENCE], config, symbol)
            for symbol in TRADED
        }
        route = {
            'config': asdict(config),
            'raw_candidates_by_window': _candidate_counts(raw),
            'windows': {'development': {}},
        }
        for scenario in ('base', 'stress', 'severe'):
            summary, trades = _run_window(data, raw, config, scenario, WINDOWS['development'])
            route['windows']['development'][scenario] = summary
            payload = json.dumps(trades, allow_nan=False).encode()
            (output / f'{config.route}_development_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
            print(config.route, scenario, summary['trades'], summary['profit_factor'],
                  f'${summary["net_pnl"]:.2f}', flush=True)
        if not _development_pass(route['windows']['development']['base']):
            route['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
            results[config.route] = route
            continue

        route['windows']['validation'] = {}
        for scenario in ('base', 'stress', 'severe'):
            summary, trades = _run_window(data, raw, config, scenario, WINDOWS['validation'])
            route['windows']['validation'][scenario] = summary
            payload = json.dumps(trades, allow_nan=False).encode()
            (output / f'{config.route}_validation_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
        if not _validation_pass(
            route['windows']['validation']['base'], route['windows']['validation']['stress']):
            route['decision'] = 'REJECTED_AT_VALIDATION_GATE'
            results[config.route] = route
            continue

        route['windows']['retrospective_evaluation'] = {}
        for scenario in ('base', 'stress', 'severe'):
            summary, trades = _run_window(
                data, raw, config, scenario, WINDOWS['retrospective_evaluation'])
            route['windows']['retrospective_evaluation'][scenario] = summary
            payload = json.dumps(trades, allow_nan=False).encode()
            (output / f'{config.route}_evaluation_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
        route['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
        results[config.route] = route

    document = {
        'protocol_sha256': protocol_hash,
        'disclosure': 'retrospective approve-all queue; no AI verdicts and no untouched holdout',
        'results': results,
    }
    (output / 'summary.json').write_text(json.dumps(document, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(results, protocol_hash))


if __name__ == '__main__':
    main()
