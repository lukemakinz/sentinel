"""S114: OB Liquidity Reversal on a point-in-time universe of 48 mid-cap alts."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import gzip
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.ob_liquidity_reversal import OBLiquidityReversalConfig, ob_liquidity_reversal_signals
from .broad_universe import load_available_minutes
from .cluster_scalp_simulator import execute_cluster
from .sharpe_stats import deflated_sharpe

WARMUP, END = '2025-04-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-05-01', '2025-10-01'),
    'validation': ('2025-10-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}
ROUTES = {
    'STRICT': OBLiquidityReversalConfig(target_mode='nearest'),
    'EXTERNAL': OBLiquidityReversalConfig(target_mode='first_at_min_r'),
    'ABSORB_CVD': OBLiquidityReversalConfig(
        target_mode='first_at_min_r', require_absorption=True, discount_fraction=1 / 3),
}
FEES = {'base': (2, 5), 'stress': (5, 8), 'severe': (10, 10)}
SLIPPAGE = {'tier_1': {'base': 2, 'stress': 5, 'severe': 10},
            'tier_2': {'base': 5, 'stress': 10, 'severe': 20},
            'tier_3': {'base': 10, 'stress': 20, 'severe': 40}}
PRIOR_TRIALS = 133 + 3


def _execution(config, scenario, tier):
    maker, taker = FEES[scenario]
    slip = SLIPPAGE[tier][scenario]
    return replace(config.execution(), maker_fee_bps=maker, fee_bps=taker,
                   slippage_bps=slip, limit_penetration_bps=slip)


def _symbol_job(args):
    """Load one symbol, build signals for every route, simulate every window."""
    symbol, tier, cache = args
    try:
        minutes, funding, data_end, _ = load_available_minutes(symbol, WARMUP, END, cache)
    except Exception as exc:
        return symbol, {'excluded': f'{type(exc).__name__}: {exc}'}
    out = {'tier': tier, 'data_end': str(data_end), 'routes': {}}
    for route, config in ROUTES.items():
        signals, audit = ob_liquidity_reversal_signals(minutes, config)
        out['routes'][route] = {'signals': len(signals), 'audit': audit, 'windows': {}}
        for window, (start, end) in WINDOWS.items():
            start_ts = pd.Timestamp(start, tz='UTC')
            end_ts = min(pd.Timestamp(end, tz='UTC'), data_end)
            if end_ts <= start_ts:
                continue
            out['routes'][route]['windows'][window] = {}
            for scenario in FEES:
                try:
                    replay = execute_cluster(
                        {symbol: (minutes, funding)}, {symbol: signals},
                        _execution(config, scenario, tier), start_ts, end_ts,
                        initial_capital=250.0, symbol_priority=(symbol,))
                except Exception as exc:  # reported, never silently dropped
                    out.setdefault('window_errors', {})[f'{route}:{window}:{scenario}'] = (
                        f'{type(exc).__name__}: {exc}')
                    continue
                out['routes'][route]['windows'][window][scenario] = [
                    {'r': t['r_multiple'], 'pnl': t['pnl'], 'opened_at': t['opened_at'],
                     'side': t['side'], 'reason': t['reason']}
                    for t in replay['trades']]
    return symbol, out


def _stats(trades):
    r = np.array([t['r'] for t in trades], dtype=float)
    if not len(r):
        return {'trades': 0, 'mean_net_r': None, 'profit_factor_r': None, 'win_rate': None}
    gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
    return {'trades': int(len(r)), 'mean_net_r': float(r.mean()),
            'profit_factor_r': float(gains / losses) if losses else None,
            'win_rate': float((r > 0).mean()), 'total_r': float(r.sum()),
            'pnl_usd': float(sum(t['pnl'] for t in trades))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s114_ob_reversal_broad_alts')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    output = Path(args.output)
    protocol_hash = sha256((output / 'protocol.json').read_bytes()).hexdigest()
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')
    universe = json.loads((output / 'universe.json').read_text())['symbols']

    jobs = [(s, meta['tier'], args.cache) for s, meta in universe.items()]
    per_symbol = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for symbol, result in pool.map(_symbol_job, jobs):
            per_symbol[symbol] = result
            print(symbol, result.get('excluded') or result['data_end'], flush=True)

    included = {s: r for s, r in per_symbol.items() if 'excluded' not in r}
    summary = {'protocol_sha256': protocol_hash, 'symbols_included': len(included),
               'excluded': {s: r['excluded'] for s, r in per_symbol.items() if 'excluded' in r},
               'window_errors': {s: r['window_errors'] for s, r in per_symbol.items()
                                 if r.get('window_errors')},
               'routes': {}}
    for route in ROUTES:
        route_out = {'windows': {}, 'pooled': {}}
        for scenario in FEES:
            pooled, by_symbol = [], {}
            for window in WINDOWS:
                trades = [t for r in included.values()
                          for t in r['routes'][route]['windows'].get(window, {}).get(scenario, [])]
                route_out['windows'].setdefault(window, {})[scenario] = _stats(trades)
                pooled += trades
            for symbol, r in included.items():
                by_symbol[symbol] = sum(t['r'] for w in r['routes'][route]['windows'].values()
                                        for t in w.get(scenario, []))
            stats = _stats(pooled)
            positive = [v for v in by_symbol.values() if v > 0]
            stats['max_symbol_share_of_positive_r_pct'] = (
                max(positive) / sum(positive) * 100 if positive else None)
            stats['by_side'] = {side: _stats([t for t in pooled if t['side'] == side])
                                for side in ('LONG', 'SHORT')}
            if pooled:
                stats['deflated_sharpe_per_trade'] = deflated_sharpe(
                    [t['r'] for t in sorted(pooled, key=lambda t: t['opened_at'])], PRIOR_TRIALS)
            route_out['pooled'][scenario] = stats
        s, sev = route_out['pooled']['stress'], route_out['pooled']['severe']
        windows_positive = sum(1 for w in WINDOWS
                               if (route_out['windows'][w]['stress']['mean_net_r'] or 0) > 0)
        checks = {
            'trades': s['trades'] >= 100,
            'profit_factor': (s['profit_factor_r'] or 0) >= 1.15,
            'mean_net_r': (s['mean_net_r'] or -1) >= 0.08,
            'windows_positive': windows_positive >= 2,
            'severe_positive': (sev['mean_net_r'] or -1) > 0,
            'symbol_concentration': (s['max_symbol_share_of_positive_r_pct'] or 100) <= 25,
        }
        route_out['gate'] = checks
        route_out['decision'] = ('PASSED_SHADOW_FORWARD_NEXT' if all(checks.values())
                                 else 'REJECTED')
        summary['routes'][route] = route_out

    (output / 'summary.json').write_text(json.dumps(summary, indent=2, default=str) + '\n')
    (output / 'per_symbol.json.gz').write_bytes(gzip.compress(
        json.dumps(per_symbol, default=str).encode(), mtime=0))

    lines = ['# S114 — OB Liquidity Reversal on 48 point-in-time mid-cap alts', '',
             f"Protocol hash: `{protocol_hash}`. Symbols simulated: {len(included)}; "
             f"excluded: {len(summary['excluded'])}. R per trade, standalone $250 accounts.", '',
             '| Route | Window | Costs | Trades | WR | PF (R) | Mean R | Total R |',
             '|---|---|---|---:|---:|---:|---:|---:|']
    fmt = lambda v, p=2: '—' if v is None else f'{v:.{p}f}'  # noqa: E731
    for route, r in summary['routes'].items():
        rows = [(w, sc, st) for w, scs in r['windows'].items() for sc, st in scs.items()]
        rows += [('POOLED', sc, st) for sc, st in r['pooled'].items()]
        for window, scenario, st in rows:
            wr = '—' if st['win_rate'] is None else f"{st['win_rate'] * 100:.1f}%"
            lines.append(f"| {route} | {window} | {scenario} | {st['trades']} | {wr} | "
                         f"{fmt(st['profit_factor_r'])} | {fmt(st['mean_net_r'], 3)} | "
                         f"{fmt(st.get('total_r'), 1)} |")
    lines.append('')
    for route, r in summary['routes'].items():
        failed = [k for k, ok in r['gate'].items() if not ok]
        lines.append(f"- **{route}: {r['decision']}**" + (f' — failed: {failed}' if failed else ''))
    lines.extend(['', 'Retrospective research only; no live approval.', ''])
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
