"""Frozen replay for S113 OB Absorption Reversal (CONTROL, ABSORB, ABSORB_PARTIAL)."""
import argparse
from dataclasses import asdict
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
from .metrics_data import load_metrics
from .run_s90_fresh_level_sweep_reclaim import _clusters, _execution, _numeric_pf
from .scalp_data import load_archives


SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT',
           'DOGEUSDT', 'AVAXUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT', 'DOTUSDT')
WARMUP, END = '2024-08-01', '2026-09-01'
WINDOWS = {
    'in_sample_reference': ('2025-05-01', '2025-10-01'),
    'held_out': ('2025-10-01', END),
    'validation': ('2025-10-01', '2026-04-01'),
    'evaluation': ('2026-04-01', END),
}
_COMMON = dict(target_mode='first_at_min_r', max_positions=2)
ROUTES = {
    'CONTROL': OBLiquidityReversalConfig(**_COMMON),
    'ABSORB': OBLiquidityReversalConfig(
        **_COMMON, require_absorption=True, discount_fraction=1 / 3),
    'ABSORB_PARTIAL': OBLiquidityReversalConfig(
        **_COMMON, require_absorption=True, discount_fraction=1 / 3, partial_r=2.0),
}
CAPITAL = 250.0
TARGET_USD_PER_DAY = 5.0


def _gate(windows, control_held_out):
    stress, severe = windows['held_out']['stress'], windows['held_out']['severe']
    checks = {
        'fills': stress['trades'] >= 60,
        'clusters': stress['independent_4h_clusters'] >= 30,
        'profit_factor': _numeric_pf(stress) >= 1.15,
        'mean_net_r': stress['mean_net_r'] >= 0.08,
        'stress_pnl_positive': stress['net_pnl'] > 0,
        'severe_pnl_positive': severe['net_pnl'] > 0,
        'drawdown': stress['max_drawdown_pct'] <= 6.0,
        'subwindows_pf': all(
            _numeric_pf(windows[w]['stress']) >= 1.0 for w in ('validation', 'evaluation')),
        'beats_control': stress['mean_net_r'] > control_held_out['mean_net_r'],
    }
    return all(checks.values()), checks


def _days(bounds):
    return (pd.Timestamp(bounds[1]) - pd.Timestamp(bounds[0])).days


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s113_ob_absorption_reversal')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    if not protocol.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before replay')
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    markets, open_interest, manifest = {}, {}, {}
    for symbol in SYMBOLS:
        minutes, funding, sources = load_archives(symbol, WARMUP, END, args.cache)
        metrics, metric_sources = load_metrics(symbol, WARMUP, END, args.cache)
        markets[symbol] = (minutes, funding)
        open_interest[symbol] = metrics.open_interest
        manifest[symbol] = {'klines_funding': sources, 'metrics_days': len(metric_sources)}
        print('loaded', symbol, flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    result = {'protocol_sha256': protocol_hash, 'routes': {},
              'disclosure': 'retrospective research only'}
    audits = {}
    for route, config in ROUTES.items():
        signals = {}
        for symbol in SYMBOLS:
            signals[symbol], audits[f'{route}:{symbol}'] = ob_liquidity_reversal_signals(
                markets[symbol][0], config, open_interest[symbol])
        print(route, sum(map(len, signals.values())), 'signals', flush=True)
        route_result = {'config': asdict(config),
                        'signals': {s: len(x) for s, x in signals.items()},
                        'windows': {}}
        for window, bounds in WINDOWS.items():
            route_result['windows'][window] = {}
            for scenario in ('base', 'stress', 'severe'):
                replay = execute_cluster(
                    markets, signals, _execution(config, scenario), *bounds,
                    initial_capital=CAPITAL, symbol_priority=SYMBOLS)
                summary = dict(replay['summary'])
                summary['independent_4h_clusters'] = _clusters(replay['trades'])
                summary['usd_per_day'] = summary['net_pnl'] / _days(bounds)
                summary['gap_to_target_usd_per_day'] = (
                    TARGET_USD_PER_DAY - summary['usd_per_day'])
                summary['by_side'] = {
                    side: {
                        'trades': len(rows),
                        'mean_net_r': (sum(t['r_multiple'] for t in rows) / len(rows)
                                       if rows else None),
                    }
                    for side in ('LONG', 'SHORT')
                    for rows in [[t for t in replay['trades'] if t['side'] == side]]
                }
                route_result['windows'][window][scenario] = summary
                (output / f'{route}_{window}_{scenario}_trades.json.gz').write_bytes(
                    gzip.compress(json.dumps(
                        replay['trades'], allow_nan=False, default=str).encode(), mtime=0))
                print(route, window, scenario, summary['trades'],
                      summary['profit_factor'], round(summary['mean_net_r'], 3),
                      round(summary['net_pnl'], 2), flush=True)
        result['routes'][route] = route_result

    control = result['routes']['CONTROL']['windows']['held_out']['stress']
    for route in ('ABSORB', 'ABSORB_PARTIAL'):
        passed, checks = _gate(result['routes'][route]['windows'], control)
        result['routes'][route]['gate'] = checks
        result['routes'][route]['decision'] = (
            'HELD_OUT_GATE_PASSED_SHADOW_FORWARD_NEXT' if passed
            else 'REJECTED_AT_HELD_OUT_GATE')
    result['routes']['CONTROL']['decision'] = 'CONTROL_NOT_PROMOTABLE'

    (output / 'state_audit.json').write_text(json.dumps(audits, indent=2) + '\n')
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False, default=str) + '\n')

    lines = ['# S113 — OB Absorption Reversal', '', f'Protocol hash: `{protocol_hash}`.', '',
             'Capital $250, risk 0.2% per trade, up to 2 positions, 12 symbols; 1m execution',
             'with fees, slippage and funding. Target for comparison: $5/day.', '',
             '| Route | Window | Costs | Fills | WR | PF | Mean R | PnL | $/day | Gap to $5/day | Max DD |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for route, route_result in result['routes'].items():
        for window, scenarios in route_result['windows'].items():
            for scenario, row in scenarios.items():
                pf = row['profit_factor']
                pf = f'{pf:.2f}' if isinstance(pf, float) else (pf or '—')
                lines.append(
                    f'| {route} | {window} | {scenario} | {row["trades"]} | '
                    f'{row["win_rate_pct"]:.1f}% | {pf} | {row["mean_net_r"]:.3f} | '
                    f'${row["net_pnl"]:.2f} | ${row["usd_per_day"]:.3f} | '
                    f'${row["gap_to_target_usd_per_day"]:.2f} | {row["max_drawdown_pct"]:.2f}% |')
    lines.append('')
    for route, route_result in result['routes'].items():
        gate = route_result.get('gate')
        failed = [k for k, ok in (gate or {}).items() if not ok]
        lines.append(f'- **{route}: {route_result["decision"]}**'
                     + (f' — failed checks: {failed}' if failed else ''))
    lines.extend(['', 'Retrospective research only; no live approval.', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
