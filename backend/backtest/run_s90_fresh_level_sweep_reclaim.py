"""Frozen causal replay for S90 Fresh Level Sweep-Reclaim."""
import argparse
from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.fresh_level_sweep_reclaim import (
    FreshLevelSweepReclaimConfig,
    fresh_level_candidates,
)
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives
from .sweep_reclaim_orders import materialize_sweep_reclaims


SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT',
           'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT')
WARMUP, END = '2024-08-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}


def _execution(config, scenario):
    base = config.execution()
    if scenario == 'stress':
        return replace(base, maker_fee_bps=5, fee_bps=8, slippage_bps=5,
                       limit_penetration_bps=5)
    if scenario == 'severe':
        return replace(base, maker_fee_bps=10, fee_bps=10, slippage_bps=10,
                       limit_penetration_bps=10)
    return base


def _numeric_pf(summary):
    value = summary['profit_factor']
    return float('inf') if value == 'Infinity' else (float(value) if value is not None else 0.0)


def _clusters(trades):
    return len({pd.Timestamp(trade['opened_at']).floor('4h') for trade in trades})


def _passes(window, replay):
    summary, clusters = replay['summary'], _clusters(replay['trades'])
    minimum_fills = 80 if window == 'development' else 50
    minimum_clusters = 40 if window == 'development' else 25
    minimum_pf = 1.20 if window == 'development' else 1.15
    minimum_r = 0.10 if window == 'development' else 0.08
    return (
        summary['trades'] >= minimum_fills
        and clusters >= minimum_clusters
        and summary['net_pnl'] > 0
        and _numeric_pf(summary) >= minimum_pf
        and summary['mean_net_r'] >= minimum_r
        and summary['max_drawdown_pct'] <= 6.0
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s90_fresh_level_sweep_reclaim')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    config = FreshLevelSweepReclaimConfig()
    markets, levels, signals, audits, manifest = {}, {}, {}, {}, {}
    for symbol in SYMBOLS:
        minutes, funding, sources = load_archives(symbol, WARMUP, END, args.cache)
        markets[symbol] = (minutes, funding)
        manifest[symbol] = sources
        _, levels[symbol] = fresh_level_candidates(minutes, config)
        signals[symbol], audits[symbol] = materialize_sweep_reclaims(
            minutes, levels[symbol], config,
            stress_fee_bps=8, stress_slippage_bps=5)
        print(symbol, len(levels[symbol]), 'levels', len(signals[symbol]), 'triggers', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'state_audit.json').write_text(json.dumps(audits, indent=2) + '\n')

    result = {
        'protocol_sha256': protocol_hash,
        'config': asdict(config),
        'raw_levels': {symbol: len(items) for symbol, items in levels.items()},
        'triggers': {symbol: len(items) for symbol, items in signals.items()},
        'windows': {},
        'disclosure': 'retrospective research only; no live approval',
    }
    decision = 'PENDING'
    for window, bounds in WINDOWS.items():
        result['windows'][window] = {}
        window_replays = {}
        for scenario in ('base', 'stress', 'severe'):
            replay = execute_cluster(
                markets, signals, _execution(config, scenario), *bounds,
                initial_capital=100.0, symbol_priority=SYMBOLS)
            window_replays[scenario] = replay
            summary = dict(replay['summary'])
            summary['independent_4h_clusters'] = _clusters(replay['trades'])
            result['windows'][window][scenario] = summary
            payload = json.dumps(replay['trades'], allow_nan=False).encode()
            (output / f'{window}_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(payload, mtime=0))
            print(window, scenario, summary['trades'], summary['profit_factor'],
                  summary['net_pnl'], flush=True)
        if not _passes(window, window_replays['stress']):
            decision = f'REJECTED_AT_{window.upper()}_GATE'
            break
    else:
        decision = 'HISTORICAL_GATES_PASSED_PAPER_FORWARD_ONLY'
    result['decision'] = decision
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')

    lines = [
        '# S90 — Fresh Level Sweep-Reclaim', '',
        f'Protocol hash: `{protocol_hash}`.', '',
        '| Window | Costs | Fills | Clusters | PF | Mean R | PnL | Return | Max DD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window, scenarios in result['windows'].items():
        for scenario, row in scenarios.items():
            pf = row['profit_factor'] if row['profit_factor'] is not None else '—'
            lines.append(
                f'| {window} | {scenario} | {row["trades"]} | '
                f'{row["independent_4h_clusters"]} | {pf} | {row["mean_net_r"]:.3f} | '
                f'${row["net_pnl"]:.2f} | {row["return_pct"]:.2f}% | '
                f'{row["max_drawdown_pct"]:.2f}% |')
    lines.extend(['', f'**Decision: {decision}.**', '',
                  'Retrospective research only; no guarantee of profit and no live approval.', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
