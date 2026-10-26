"""Run the protocol-frozen S32 XFRD Binance/Bybit replay."""
import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from .xfrd import XFRDConfig, XFRDCosts, simulate_xfrd
from .xfrd_data import load_xfrd_venues


SYMBOLS = ('ETHUSDT', 'SOLUSDT')
WARMUP_START = '2022-12-01'
END = '2026-09-01'
WINDOWS = {
    'development': ('2023-01-01', '2024-01-01'),
    'validation': ('2024-01-01', '2025-01-01'),
    'retrospective_evaluation': ('2025-01-01', END),
    'all_available': ('2023-01-01', END),
}
INITIAL_CAPITAL = 250.0


def _numeric_pf(value):
    if value == 'Infinity':
        return float('inf')
    return float(value or 0.0)


def _historical_gate(results: dict) -> str:
    stress = results['stress']
    named = ('development', 'validation', 'retrospective_evaluation')
    if any(stress[window]['summary']['net_pnl'] <= 0 for window in named):
        return 'REJECTED_BY_STRESS_NET_WINDOW_GATE'
    if any(stress[window]['summary']['funding_minus_costs'] <= 0 for window in named):
        return 'REJECTED_BY_FUNDING_EDGE_WINDOW_GATE'
    combined = stress['all_available']['summary']
    if combined['episodes'] < 30:
        return 'INCONCLUSIVE_TOO_FEW_EPISODES'
    if any(stress[window]['summary']['episodes'] < 8
           for window in ('validation', 'retrospective_evaluation')):
        return 'INCONCLUSIVE_TOO_FEW_VALIDATION_EPISODES'
    if combined['collateral_exhaustions']:
        return 'REJECTED_BY_COLLATERAL_EXHAUSTION'
    if min(combined['min_venue_equity'].values()) < 75.0:
        return 'REJECTED_BY_VENUE_EQUITY_GATE'
    if max(combined['max_venue_mark_leverage'].values()) > .80:
        return 'REJECTED_BY_VENUE_LEVERAGE_GATE'
    if combined['max_drawdown_pct'] > 5.0:
        return 'REJECTED_BY_DRAWDOWN_GATE'
    share = combined['largest_positive_symbol_share_pct']
    if share is None or share > 70.0:
        return 'REJECTED_BY_SYMBOL_CONCENTRATION_GATE'
    return 'HISTORICAL_GATE_PASS_PAPER_FORWARD_ONLY'


def _quality(data: dict) -> dict:
    result = {}
    for symbol, venues in data.items():
        result[symbol] = {}
        for venue, streams in venues.items():
            result[symbol][venue] = {
                'trade_h1_rows': len(streams['trade']),
                'trade_start': str(streams['trade'].index.min()),
                'trade_end': str(streams['trade'].index.max()),
                'mark_h1_rows': len(streams['mark']),
                'mark_start': str(streams['mark'].index.min()),
                'mark_end': str(streams['mark'].index.max()),
                'funding_settlements': len(streams['funding']),
                'funding_start': str(streams['funding'].index.min()),
                'funding_end': str(streams['funding'].index.max()),
            }
    return result


def _capital_projection(results: dict) -> dict:
    start, end = WINDOWS['retrospective_evaluation']
    days = (pd.Timestamp(end) - pd.Timestamp(start)).days
    projection = {}
    for scenario in ('base', 'stress'):
        net = results[scenario]['retrospective_evaluation']['summary']['net_pnl']
        daily = net / days
        projection[scenario] = {
            'window_days': days,
            'average_daily_pnl_usd_on_250': daily,
            'linear_capital_for_25_usd_per_day': (
                INITIAL_CAPITAL * 25 / daily if daily > 0 else None),
            'warning': 'linear diagnostic only; not a forecast or capacity estimate',
        }
    return projection


def _report(results: dict, protocol_hash: str, decision: str,
            projection: dict) -> str:
    lines = [
        '# S32 XFRD — Binance/Bybit funding dispersion + basis', '',
        f'Frozen protocol hash: `{protocol_hash}`.', '',
        '| Window | Costs | Episodes | WR | PF | Funding | Basis PnL | Fees | Slippage | Funding-cost | Net | Return | DD | Min venue equity | Max venue lev |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window in WINDOWS:
        for scenario in ('base', 'stress'):
            summary = results[scenario][window]['summary']
            lines.append(
                f'| {window} | {scenario} | {summary["episodes"]} | '
                f'{summary["win_rate_pct"]:.1f}% | {summary["profit_factor"]} | '
                f'${summary["funding_pnl"]:.2f} | '
                f'${summary["reference_basis_price_pnl"]:.2f} | '
                f'${summary["fees"]:.2f} | ${summary["slippage_cost"]:.2f} | '
                f'${summary["funding_minus_costs"]:.2f} | '
                f'${summary["net_pnl"]:.2f} | {summary["return_pct"]:.3f}% | '
                f'{summary["max_drawdown_pct"]:.3f}% | '
                f'${min(summary["min_venue_equity"].values()):.2f} | '
                f'{max(summary["max_venue_mark_leverage"].values()):.3f}x |'
            )
    lines.extend(['', f'Decision: **{decision}**.', '', '## $25/day check', ''])
    for scenario in ('base', 'stress'):
        row = projection[scenario]
        capital = row['linear_capital_for_25_usd_per_day']
        capital_text = 'not applicable' if capital is None else f'${capital:,.0f}'
        lines.append(
            f'- {scenario}: newest window average '
            f'${row["average_daily_pnl_usd_on_250"]:.5f}/day on $250; '
            f'linear $25/day capital diagnostic: {capital_text}.'
        )
    lines.extend([
        '',
        'This is an H1 retrospective replay. It separately accounts for both '
        'venue balances, realized funding, cross-venue basis PnL, fees, adverse '
        'slippage and venue mark leverage. It cannot model order-book queue, '
        'partial one-leg fills, API outages, ADL or withdrawal freezes. Even a '
        'historical pass authorizes paper-forward only.',
    ])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binance-cache', default='/tmp/sentinel-swing-cache')
    parser.add_argument('--bybit-cache', default='/tmp/sentinel-xfrd-cache')
    parser.add_argument('--output', default='docs/research/s32_xfrd')
    parser.add_argument('--download-bybit', action='store_true')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    recorded_hash = (output / 'protocol.sha256').read_text().split()[0]
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != recorded_hash:
        raise ValueError('Frozen S32 protocol hash mismatch')

    data, manifest = {}, {}
    for symbol in SYMBOLS:
        data[symbol], manifest[symbol] = load_xfrd_venues(
            symbol, WARMUP_START, END, args.bybit_cache,
            download_bybit=args.download_bybit,
            binance_cache=args.binance_cache,
        )
        print(symbol, 'Binance/Bybit data ready', flush=True)
    (output / 'manifest.json').write_text(
        json.dumps(manifest, indent=2) + '\n')
    (output / 'data_quality.json').write_text(
        json.dumps(_quality(data), indent=2) + '\n')

    base = XFRDConfig()
    stress = replace(base, costs=XFRDCosts(fee_bps=5, slippage_bps=5))
    if stress.costs.combined_round_trip_bps != 40:
        raise AssertionError('Frozen stress round-trip must be 40 bps')
    scenarios = {'base': base, 'stress': stress}
    results = {}
    for scenario, config in scenarios.items():
        results[scenario] = {}
        for window, bounds in WINDOWS.items():
            replay = simulate_xfrd(
                data, *bounds, config, initial_capital=INITIAL_CAPITAL)
            results[scenario][window] = replay
            summary = replay['summary']
            print(scenario, window, 'episodes', summary['episodes'],
                  'funding-cost', f'${summary["funding_minus_costs"]:.2f}',
                  'net', f'${summary["net_pnl"]:.2f}', flush=True)

    decision = _historical_gate(results)
    projection = _capital_projection(results)
    payload = {
        'protocol_sha256': actual_hash,
        'decision': decision,
        'configs': {name: asdict(config) for name, config in scenarios.items()},
        'capital_projection': projection,
        'disclosure': (
            'retrospective public-data replay; no untouched holdout and no live approval'),
        'results': results,
    }
    (output / 'results.json').write_text(json.dumps(
        payload, indent=2, default=str, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(
        _report(results, actual_hash, decision, projection))


if __name__ == '__main__':
    main()
