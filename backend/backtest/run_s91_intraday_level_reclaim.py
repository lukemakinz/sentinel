"""Frozen replay for S91 intraday first-contact reclaim."""
from dataclasses import asdict

from l1_filter.fresh_level_sweep_reclaim import fresh_level_candidates
from l1_filter.intraday_level_reclaim import (
    IntradayLevelReclaimConfig,
    btc_sma200_regime_filter,
)
from .run_s90_fresh_level_sweep_reclaim import (
    SYMBOLS, _execution, _numeric_pf, _clusters,
)

import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path

from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives
from .sweep_reclaim_orders import materialize_sweep_reclaims


WARMUP, END = '2024-08-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}


def _passes(window, replay):
    summary, clusters = replay['summary'], _clusters(replay['trades'])
    return (
        summary['trades'] >= (80 if window == 'development' else 50)
        and clusters >= (40 if window == 'development' else 25)
        and summary['net_pnl'] > 0
        and _numeric_pf(summary) >= (1.20 if window == 'development' else 1.15)
        and summary['mean_net_r'] >= (0.10 if window == 'development' else 0.08)
        and summary['max_drawdown_pct'] <= 6.0
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s91_intraday_level_reclaim')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    config = IntradayLevelReclaimConfig()
    markets, manifest = {}, {}
    for symbol in SYMBOLS:
        minutes, funding, sources = load_archives(symbol, WARMUP, END, args.cache)
        markets[symbol] = (minutes, funding)
        manifest[symbol] = sources
    btc_minutes = markets['BTCUSDT'][0]
    levels, signals, audits = {}, {}, {}
    for symbol in SYMBOLS:
        _, raw = fresh_level_candidates(markets[symbol][0], config)
        levels[symbol] = btc_sma200_regime_filter(raw, btc_minutes)
        signals[symbol], audits[symbol] = materialize_sweep_reclaims(
            markets[symbol][0], levels[symbol], config,
            stress_fee_bps=8, stress_slippage_bps=5)
        print(symbol, len(raw), 'raw', len(levels[symbol]), 'regime levels',
              len(signals[symbol]), 'triggers', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'state_audit.json').write_text(json.dumps(audits, indent=2) + '\n')

    result = {
        'protocol_sha256': protocol_hash, 'config': asdict(config),
        'regime_levels': {s: len(x) for s, x in levels.items()},
        'triggers': {s: len(x) for s, x in signals.items()},
        'windows': {}, 'disclosure': 'retrospective research only',
    }
    for window, bounds in WINDOWS.items():
        result['windows'][window] = {}
        replays = {}
        for scenario in ('base', 'stress', 'severe'):
            replay = execute_cluster(
                markets, signals, _execution(config, scenario), *bounds,
                initial_capital=100.0, symbol_priority=SYMBOLS)
            replays[scenario] = replay
            summary = dict(replay['summary'])
            summary['independent_4h_clusters'] = _clusters(replay['trades'])
            result['windows'][window][scenario] = summary
            (output / f'{window}_{scenario}_trades.json.gz').write_bytes(
                gzip.compress(json.dumps(replay['trades'], allow_nan=False).encode(), mtime=0))
            print(window, scenario, summary['trades'], summary['profit_factor'],
                  summary['mean_net_r'], summary['net_pnl'], flush=True)
        if not _passes(window, replays['stress']):
            decision = f'REJECTED_AT_{window.upper()}_GATE'
            break
    else:
        decision = 'HISTORICAL_GATES_PASSED_PAPER_FORWARD_ONLY'
    result['decision'] = decision
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    lines = ['# S91 — Intraday Level Reclaim', '', f'Protocol hash: `{protocol_hash}`.', '',
             '| Window | Costs | Fills | Clusters | PF | Mean R | PnL | Return | Max DD |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for window, scenarios in result['windows'].items():
        for scenario, row in scenarios.items():
            pf = row['profit_factor'] if row['profit_factor'] is not None else '—'
            lines.append(
                f'| {window} | {scenario} | {row["trades"]} | '
                f'{row["independent_4h_clusters"]} | {pf} | {row["mean_net_r"]:.3f} | '
                f'${row["net_pnl"]:.2f} | {row["return_pct"]:.2f}% | '
                f'{row["max_drawdown_pct"]:.2f}% |')
    lines.extend(['', f'**Decision: {decision}.**', '',
                  'Retrospective research only; no live approval.', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
