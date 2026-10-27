"""Frozen replay for S112 OB Liquidity Reversal (STRICT and EXTERNAL routes)."""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.ob_liquidity_reversal import (
    OBLiquidityReversalConfig,
    ob_liquidity_reversal_signals,
)
from .cluster_scalp_simulator import execute_cluster
from .run_s90_fresh_level_sweep_reclaim import SYMBOLS, _clusters, _execution, _numeric_pf
from .scalp_data import load_archives


WARMUP, END = '2024-08-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}
ROUTES = {'STRICT': 'nearest', 'EXTERNAL': 'first_at_min_r'}
CAPITAL = 250.0
TARGET_USD_PER_DAY = 5.0


def _passes(window, replay):
    summary, clusters = replay['summary'], _clusters(replay['trades'])
    development = window == 'development'
    return (
        summary['trades'] >= (80 if development else 50)
        and clusters >= (40 if development else 25)
        and summary['net_pnl'] > 0
        and _numeric_pf(summary) >= (1.20 if development else 1.15)
        and summary['mean_net_r'] >= (0.10 if development else 0.08)
        and summary['max_drawdown_pct'] <= 6.0
    )


def _days(bounds):
    return (pd.Timestamp(bounds[1]) - pd.Timestamp(bounds[0])).days


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s112_ob_liquidity_reversal')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    markets, manifest = {}, {}
    for symbol in SYMBOLS:
        minutes, funding, sources = load_archives(symbol, WARMUP, END, args.cache)
        markets[symbol] = (minutes, funding)
        manifest[symbol] = sources
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    result = {'protocol_sha256': protocol_hash, 'routes': {},
              'disclosure': 'retrospective research only'}
    audits = {}
    for route, mode in ROUTES.items():
        config = OBLiquidityReversalConfig(target_mode=mode)
        signals = {}
        for symbol in SYMBOLS:
            signals[symbol], audits[f'{route}:{symbol}'] = ob_liquidity_reversal_signals(
                markets[symbol][0], config)
            print(route, symbol, len(signals[symbol]), 'signals', flush=True)
        route_result = {
            'config': asdict(config),
            'signals': {s: len(x) for s, x in signals.items()},
            'windows': {},
        }
        for window, bounds in WINDOWS.items():
            route_result['windows'][window] = {}
            replays = {}
            for scenario in ('base', 'stress', 'severe'):
                replay = execute_cluster(
                    markets, signals, _execution(config, scenario), *bounds,
                    initial_capital=CAPITAL, symbol_priority=SYMBOLS)
                replays[scenario] = replay
                summary = dict(replay['summary'])
                summary['independent_4h_clusters'] = _clusters(replay['trades'])
                summary['usd_per_day'] = summary['net_pnl'] / _days(bounds)
                summary['gap_to_target_usd_per_day'] = (
                    TARGET_USD_PER_DAY - summary['usd_per_day'])
                route_result['windows'][window][scenario] = summary
                (output / f'{route}_{window}_{scenario}_trades.json.gz').write_bytes(
                    gzip.compress(json.dumps(
                        replay['trades'], allow_nan=False, default=str).encode(), mtime=0))
                print(route, window, scenario, summary['trades'],
                      summary['profit_factor'], summary['mean_net_r'],
                      summary['net_pnl'], flush=True)
            if not _passes(window, replays['stress']):
                route_result['decision'] = f'REJECTED_AT_{window.upper()}_GATE'
                break
        else:
            route_result['decision'] = 'HISTORICAL_GATES_PASSED_BENCHMARK_AND_PAPER_FORWARD_NEXT'
        result['routes'][route] = route_result

    (output / 'state_audit.json').write_text(json.dumps(audits, indent=2) + '\n')
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False, default=str) + '\n')

    lines = ['# S112 — OB Liquidity Reversal', '', f'Protocol hash: `{protocol_hash}`.', '',
             'Capital $250, risk 0.2% per trade, one position; 1m execution with fees,',
             'slippage and funding. Target for comparison: $5/day.', '',
             '| Route | Window | Costs | Fills | Clusters | WR | PF | Mean R | PnL | $/day | Gap to $5/day | Max DD |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for route, route_result in result['routes'].items():
        for window, scenarios in route_result['windows'].items():
            for scenario, row in scenarios.items():
                pf = row['profit_factor']
                pf = f'{pf:.2f}' if isinstance(pf, float) else (pf or '—')
                lines.append(
                    f'| {route} | {window} | {scenario} | {row["trades"]} | '
                    f'{row["independent_4h_clusters"]} | {row["win_rate_pct"]:.1f}% | {pf} | '
                    f'{row["mean_net_r"]:.3f} | ${row["net_pnl"]:.2f} | '
                    f'${row["usd_per_day"]:.3f} | ${row["gap_to_target_usd_per_day"]:.2f} | '
                    f'{row["max_drawdown_pct"]:.2f}% |')
    lines.append('')
    for route, route_result in result['routes'].items():
        lines.append(f'- **{route}: {route_result["decision"]}** '
                     f'(signals per symbol: {route_result["signals"]}).')
    lines.extend(['', 'Retrospective research only; no live approval.', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
