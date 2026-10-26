"""Run the protocol-frozen S33 fixed-expiry cash-and-carry replay."""
import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from .dated_carry import DatedCarryConfig, DatedCarryCosts, simulate_dated_carry
from .dated_carry_data import load_dated_carry_market


SYMBOLS = ('BTCUSDT', 'ETHUSDT')
START, END = '2023-01-01', '2026-09-01'
WINDOWS = {
    'development': ('2023-01-01', '2024-01-01'),
    'validation': ('2024-01-01', '2025-01-01'),
    'retrospective_evaluation': ('2025-01-01', END),
    'all_available': (START, END),
}
INITIAL_CAPITAL = 250.0


def _gate(results):
    stress = results['stress']
    named = ('development', 'validation', 'retrospective_evaluation')
    if any(stress[window]['summary']['net_pnl'] <= 0 for window in named):
        return 'REJECTED_BY_STRESS_WINDOW_GATE'
    if any(stress[window]['summary']['episodes'] < 2 for window in named):
        return 'INCONCLUSIVE_TOO_FEW_EXECUTED_EXPIRIES'
    combined = stress['all_available']['summary']
    if combined['collateral_exhaustions']:
        return 'REJECTED_BY_COLLATERAL_EXHAUSTION'
    if combined['min_futures_equity_usd'] < 100:
        return 'REJECTED_BY_FUTURES_EQUITY_GATE'
    if combined['max_futures_mark_leverage'] > .80:
        return 'REJECTED_BY_FUTURES_LEVERAGE_GATE'
    if combined['max_drawdown_pct'] > 3:
        return 'REJECTED_BY_DRAWDOWN_GATE'
    per_symbol = combined['per_symbol']
    if any(row['episodes'] == 0 or row['net_pnl'] <= 0 for row in per_symbol.values()):
        return 'REJECTED_BY_SYMBOL_CONCENTRATION_GATE'
    return 'HISTORICAL_GATE_PASS_PAPER_FORWARD_ONLY'


def _projection(results):
    start, end = WINDOWS['retrospective_evaluation']
    days = (pd.Timestamp(end) - pd.Timestamp(start)).days
    output = {}
    for scenario in ('base', 'stress'):
        net = results[scenario]['retrospective_evaluation']['summary']['net_pnl']
        daily = net / days
        output[scenario] = {
            'window_days': days,
            'average_daily_pnl_usd_on_250': daily,
            'linear_capital_for_25_usd_per_day': (
                INITIAL_CAPITAL * 25 / daily if daily > 0 else None),
            'warning': 'linear diagnostic only; not a forecast or capacity estimate',
        }
    return output


def _report(results, protocol_hash, decision, projection):
    lines = [
        '# S33 — fixed-expiry cash-and-carry', '',
        f'Frozen protocol hash: `{protocol_hash}`.', '',
        '| Window | Costs | Qualified/decisions | Episodes | WR | PF | Basis PnL | Fees | Slippage | Net | Return | DD | Min futures equity | Max futures lev |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window in WINDOWS:
        for scenario in ('base', 'stress'):
            summary = results[scenario][window]['summary']
            lines.append(
                f'| {window} | {scenario} | {summary["qualified_decisions"]}/'
                f'{summary["quarterly_decisions"]} | {summary["episodes"]} | '
                f'{summary["win_rate_pct"]:.1f}% | {summary["profit_factor"]} | '
                f'${summary["reference_basis_pnl"]:.2f} | ${summary["fees"]:.2f} | '
                f'${summary["slippage_cost"]:.2f} | ${summary["net_pnl"]:.2f} | '
                f'{summary["return_pct"]:.3f}% | {summary["max_drawdown_pct"]:.3f}% | '
                f'${summary["min_futures_equity_usd"]:.2f} | '
                f'{summary["max_futures_mark_leverage"]:.3f}x |'
            )
    lines.extend(['', f'Decision: **{decision}**.', '', '## $25/day check', ''])
    for scenario in ('base', 'stress'):
        row = projection[scenario]
        capital = row['linear_capital_for_25_usd_per_day']
        text = 'not applicable' if capital is None else f'${capital:,.0f}'
        lines.append(
            f'- {scenario}: newest-window average '
            f'${row["average_daily_pnl_usd_on_250"]:.5f}/day on $250; '
            f'linear $25/day capital diagnostic: {text}.'
        )
    lines.extend([
        '',
        'The position exits one hour before expiry and never crosses a continuous '
        'contract roll. Results include distinct spot/futures fills, four fees, '
        'adverse slippage and isolated short-collateral diagnostics. H1 history '
        'cannot model order-book impact or exact maintenance-margin tiers; a '
        'historical pass would authorize paper-forward only.',
    ])
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-cache', default='/tmp/sentinel-swing-cache')
    parser.add_argument('--api-cache', default='/tmp/sentinel-dated-cache')
    parser.add_argument('--output', default='docs/research/s33_dated_carry')
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    recorded_hash = (output / 'protocol.sha256').read_text().split()[0]
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != recorded_hash:
        raise ValueError('Frozen S33 protocol hash mismatch')

    data, manifests, quality = {}, {}, {}
    for symbol in SYMBOLS:
        market, manifests[symbol] = load_dated_carry_market(
            symbol, START, END, args.api_cache,
            download_missing=args.download,
            binance_cache=args.archive_cache,
            download_spot_missing=args.download,
        )
        data[symbol] = {
            'spot': market['spot'],
            'futures': market['current_quarter'],
        }
        quality[symbol] = {
            'spot_h1_rows': len(market['spot']),
            'spot_start': str(market['spot'].index.min()),
            'spot_end': str(market['spot'].index.max()),
            'current_quarter_h1_rows': len(market['current_quarter']),
            'current_quarter_start': str(market['current_quarter'].index.min()),
            'current_quarter_end': str(market['current_quarter'].index.max()),
        }
        print(symbol, 'spot/current-quarter data ready', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifests, indent=2) + '\n')
    (output / 'data_quality.json').write_text(json.dumps(quality, indent=2) + '\n')

    base = DatedCarryConfig()
    stress = replace(base, costs=DatedCarryCosts(
        spot_fee_bps=10, futures_fee_bps=5,
        spot_slippage_bps=5, futures_slippage_bps=5))
    if stress.costs.combined_round_trip_bps != 50:
        raise AssertionError('Frozen S33 stress round-trip must be 50 bps')
    results = {}
    for scenario, config in {'base': base, 'stress': stress}.items():
        results[scenario] = {}
        for window, bounds in WINDOWS.items():
            replay = simulate_dated_carry(
                data, *bounds, config, initial_capital=INITIAL_CAPITAL)
            results[scenario][window] = replay
            summary = replay['summary']
            print(scenario, window,
                  f'{summary["qualified_decisions"]}/{summary["quarterly_decisions"]}',
                  'net', f'${summary["net_pnl"]:.2f}', flush=True)

    decision = _gate(results)
    projection = _projection(results)
    payload = {
        'protocol_sha256': actual_hash,
        'decision': decision,
        'configs': {'base': asdict(base), 'stress': asdict(stress)},
        'capital_projection': projection,
        'disclosure': 'retrospective public-data replay; no untouched holdout',
        'results': results,
    }
    (output / 'results.json').write_text(json.dumps(
        payload, indent=2, default=str, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(
        _report(results, actual_hash, decision, projection))


if __name__ == '__main__':
    main()
