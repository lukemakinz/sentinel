"""Offline, gate-by-gate retrospective for the frozen S17 order-block
continuation routes (base vs divergence). No BTC reference series is used:
regime, structure and flow are computed entirely from each traded symbol's
own price. The command refuses network access to anything but the public
Binance archive cache and never registers a live strategy.
"""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.order_block_continuation_scalp import (
    central_variants,
    generate_order_block_signals,
    order_block_features,
)
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives


TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
WARMUP, END = '2025-04-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-08-01', '2026-02-01'),
    'validation': ('2026-02-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}


def _numeric_pf(summary: dict) -> float:
    value = summary['profit_factor']
    if value == 'Infinity':
        return float('inf')
    return float(value or 0.0)


def _development_pass(summary: dict) -> bool:
    return (summary['trades'] >= 40 and summary['net_pnl'] > 0
            and _numeric_pf(summary) > 1.05)


def _validation_pass(base: dict, stress: dict) -> bool:
    contribution = base['largest_symbol_gross_profit_share_pct']
    return (
        base['trades'] >= 20
        and _numeric_pf(base) > 1.10
        and _numeric_pf(stress) >= 1.00
        and base['positive_symbols'] >= 2
        and contribution is not None and contribution <= 60
    )


def _scenario_execution(config, scenario):
    execution = config.execution()
    if scenario == 'stress':
        return replace(execution, maker_fee_bps=5.0, fee_bps=8.0,
                       slippage_bps=5.0, limit_penetration_bps=5.0)
    if scenario == 'severe':
        return replace(execution, maker_fee_bps=10.0, fee_bps=10.0,
                       slippage_bps=10.0, limit_penetration_bps=10.0)
    return execution


def _run_window(data, signals, config, scenario, start, end):
    execution = _scenario_execution(config, scenario)
    result = execute_cluster(
        {symbol: data[symbol] for symbol in TRADED}, signals, execution,
        start, end, initial_capital=250, symbol_priority=TRADED,
    )
    return result['summary'], result['trades']


def _report(results: dict, protocol_hash: str) -> str:
    lines = [
        '# S17 — Order block retest continuation (base vs OBV+dywergencja)',
        '',
        f'Hash zamrożonego protokołu: `{protocol_hash}`.',
        '',
        'To badanie retrospektywne. BTC nie jest używany — sygnał liczony wyłącznie '
        'z ceny handlowanego instrumentu. Maszyneria wyjścia identyczna jak w S16.',
        '',
        '| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for route, route_result in results.items():
        for window, scenarios in route_result['windows'].items():
            for scenario, summary in scenarios.items():
                pf = summary['profit_factor'] if summary['profit_factor'] is not None else '—'
                lines.append(
                    f'| {route} | {window} | {scenario} | {summary["trades"]} | '
                    f'{summary["win_rate_pct"]:.1f}% | {pf} | ${summary["net_pnl"]:.2f} | '
                    f'{summary["return_pct"]:.3f}% | {summary["max_drawdown_pct"]:.3f}% |'
                )
        lines.extend([
            '',
            f'- Decyzja dla `{route}`: **{route_result["decision"]}**.',
            f'- Surowe kandydaty per okno: {route_result["raw_candidates_by_window"]}.',
            '',
        ])
    lines.extend([
        '## Interpretacja',
        '',
        'Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako '
        '„najmniej zła”. Divergence (H2) jest ściśle podzbiorem base (H1).',
        '',
        'Kapitał: $250; jeden wspólny cash/pending/position; stałe ryzyko $0,50; '
        'notional do $125; dźwignia do 5x. Base 2/5/2 bps (maker/taker/slippage), '
        'stress 5/8/5, severe 10/10/10.',
        '',
    ])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s17_order_block_continuation')
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    protocol_path = output / 'protocol.json'
    if not protocol_path.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before any data are loaded')
    protocol_hash = sha256(protocol_path.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')
    output.mkdir(parents=True, exist_ok=True)

    configs = central_variants()
    data, manifest = {}, {}
    for symbol in TRADED:
        minutes, funding, manifest[symbol] = load_archives(symbol, WARMUP, END, str(cache))
        data[symbol] = minutes, funding
        print(symbol, 'archives ready', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    window_bounds = {
        name: (pd.Timestamp(bounds[0], tz='UTC'), pd.Timestamp(bounds[1], tz='UTC'))
        for name, bounds in WINDOWS.items()
    }

    all_results = {}
    for config in configs:
        features = {symbol: order_block_features(data[symbol][0], config) for symbol in TRADED}
        raw = {
            symbol: generate_order_block_signals(features[symbol], config, symbol)
            for symbol in TRADED
        }
        route_result = {
            'config': asdict(config),
            'raw_candidates_by_window': {
                window: sum(
                    start <= signal['timestamp'] < end
                    for signals in raw.values() for signal in signals
                )
                for window, (start, end) in window_bounds.items()
            },
            'windows': {},
        }
        for window in ('development',):
            route_result['windows'][window] = {}
            for scenario in ('base', 'stress', 'severe'):
                summary, trades = _run_window(data, raw, config, scenario, *WINDOWS[window])
                route_result['windows'][window][scenario] = summary
                payload = json.dumps(trades, allow_nan=False).encode()
                (output / f'{config.route}_{window}_{scenario}_trades.json.gz').write_bytes(
                    gzip.compress(payload, mtime=0))
                print(config.route, window, scenario, summary['trades'],
                      summary['profit_factor'], f'${summary["net_pnl"]:.2f}', flush=True)

        dev = route_result['windows']['development']['base']
        if not _development_pass(dev):
            route_result['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
            all_results[config.route] = route_result
            continue

        route_result['windows']['validation'] = {}
        for scenario in ('base', 'stress', 'severe'):
            summary, trades = _run_window(data, raw, config, scenario, *WINDOWS['validation'])
            route_result['windows']['validation'][scenario] = summary
            payload = json.dumps(trades, allow_nan=False).encode()
            (output / f'{config.route}_validation_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
        validation = route_result['windows']['validation']
        if not _validation_pass(validation['base'], validation['stress']):
            route_result['decision'] = 'REJECTED_AT_VALIDATION_GATE'
            all_results[config.route] = route_result
            continue

        route_result['windows']['retrospective_evaluation'] = {}
        for scenario in ('base', 'stress', 'severe'):
            summary, trades = _run_window(
                data, raw, config, scenario, *WINDOWS['retrospective_evaluation'])
            route_result['windows']['retrospective_evaluation'][scenario] = summary
            payload = json.dumps(trades, allow_nan=False).encode()
            (output / f'{config.route}_evaluation_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
        route_result['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'
        all_results[config.route] = route_result

    result = {
        'protocol_sha256': protocol_hash,
        'disclosure': 'retrospective diagnostic; not a live paper-forward result',
        'results': all_results,
    }
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_report(all_results, protocol_hash))


if __name__ == '__main__':
    main()
