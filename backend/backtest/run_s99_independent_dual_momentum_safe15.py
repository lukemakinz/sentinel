"""Frozen continuous replay for S99, the 15%-vol risk repair of S98."""
import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from l1_filter.independent_dual_momentum import (
    IndependentDualMomentumConfig,
    weekly_independent_momentum_targets,
)
from .run_s97_dual_horizon_trend import (
    COSTS, END, SLICES, START, SYMBOLS, WARMUP,
    _block_bootstrap, _monthly_dispersion, _slice_metrics,
)
from .swing_data import load_interval_archives
from .trend_carry_portfolio import simulate_trend_portfolio


PROTOCOL_SHA256 = '3cb21e1f942f2ede0f274a6e413ba23c22a1ea3c59e720602b7d6d6627bee9a1'


def _report(result):
    lines = [
        '# S99 — independent dual momentum, safe 15% vol', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        'Risk-only repair of S98. All periods are contaminated historical diagnostics.', '',
        '| Period | Costs | PnL | Return | $/day | DD | Sharpe | Positive months |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for name, scenarios in result['slices'].items():
        for scenario, row in scenarios.items():
            lines.append(
                f'| {name} | {scenario} | ${row["net_pnl"]:.2f} | '
                f'{row["return_on_start_nav_pct"]:.2f}% | ${row["usd_per_calendar_day"]:.3f} | '
                f'{row["max_continuous_drawdown_pct"]:.2f}% | {row["annualized_sharpe"]:.2f} | '
                f'{row["positive_month_share"]:.1%} |')
    lines.extend(['', '## Full continuous replay', '',
                  '| Costs | PnL | Return | DD | Sharpe | Funding | Fees | Slippage |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|'])
    for scenario, row in result['continuous_replays'].items():
        lines.append(
            f'| {scenario} | ${row["net_pnl"]:.2f} | {row["return_pct"]:.2f}% | '
            f'{row["max_drawdown_pct"]:.2f}% | {row["annualized_sharpe"]:.2f} | '
            f'${row["funding_pnl"]:.2f} | ${row["fees"]:.2f} | ${row["slippage"]:.2f} |')
    lines.extend([
        '', '## Frozen robustness checks', '',
        f'- Vol-target neighbors: `{result["risk_target_neighbor_stress"]}`.',
        f'- Momentum neighbors: `{result["momentum_neighbor_stress"]}`.',
        f'- Rebalance phases: `{result["phase_stress"]}`.',
        f'- Leave-one-symbol-out: `{result["leave_one_symbol_out_stress"]}`.',
        f'- 28-day block bootstrap: `{result["stress_block_bootstrap"]}`.',
        '', f'**Decision: {result["decision"]}.**', '',
        'Historical passage authorizes only a prospective paper challenger, never a profit guarantee.', '',
    ])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s99_independent_dual_momentum_safe15')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    protocol_hash = sha256(protocol.read_bytes()).hexdigest()
    if protocol_hash != PROTOCOL_SHA256:
        raise ValueError(f'Protocol changed after freeze: expected {PROTOCOL_SHA256}, got {protocol_hash}')
    (output / 'protocol.sha256').write_text(f'{protocol_hash}  protocol.json\n')

    daily, funding, manifest = {}, {}, {}
    for symbol in SYMBOLS:
        daily[symbol], funding[symbol], manifest[symbol] = load_interval_archives(
            symbol, WARMUP, END, args.cache, interval='1d')
        print(symbol, len(daily[symbol]), 'verified daily candles', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    markets = {symbol: (daily[symbol], funding[symbol]) for symbol in SYMBOLS}
    config = replace(
        IndependentDualMomentumConfig(), portfolio_vol_target_annual=0.15)
    targets = weekly_independent_momentum_targets(
        daily, funding, START, END, config, symbol_order=SYMBOLS)

    result = {
        'protocol_sha256': protocol_hash, 'config': asdict(config),
        'weekly_decisions': len(targets),
        'invested_decisions': sum(bool(target['weights']) for target in targets),
        'continuous_replays': {}, 'slices': {},
        'risk_target_neighbor_stress': {}, 'momentum_neighbor_stress': {},
        'phase_stress': {}, 'leave_one_symbol_out_stress': {},
    }
    replays = {}
    for scenario, costs in COSTS.items():
        replay = simulate_trend_portfolio(markets, targets, START, END, 500.0, costs)
        replays[scenario] = replay
        result['continuous_replays'][scenario] = replay['summary']
        for name, bounds in SLICES.items():
            result['slices'].setdefault(name, {})[scenario] = _slice_metrics(
                replay['daily_pnl'], *bounds)
        print(scenario, replay['summary'], flush=True)

    stress_daily = replays['stress']['daily_pnl']
    result['stress_monthly_dispersion'] = _monthly_dispersion(stress_daily)
    result['stress_block_bootstrap'] = _block_bootstrap(stress_daily)
    pd.DataFrame({name: replay['daily_pnl'] for name, replay in replays.items()}).to_csv(
        output / 'daily_pnl.csv', index_label='timestamp')

    for vol_target in (0.125, 0.175):
        neighbor = replace(config, portfolio_vol_target_annual=vol_target)
        neighbor_targets = weekly_independent_momentum_targets(
            daily, funding, START, END, neighbor, symbol_order=SYMBOLS)
        replay = simulate_trend_portfolio(
            markets, neighbor_targets, START, END, 500.0, COSTS['stress'])
        result['risk_target_neighbor_stress'][str(vol_target)] = {
            'net_pnl': replay['summary']['net_pnl'],
            'max_drawdown_pct': replay['summary']['max_drawdown_pct'],
        }

    for momentum_days in (63, 126):
        neighbor = replace(config, momentum_days=momentum_days)
        neighbor_targets = weekly_independent_momentum_targets(
            daily, funding, START, END, neighbor, symbol_order=SYMBOLS)
        replay = simulate_trend_portfolio(
            markets, neighbor_targets, START, END, 500.0, COSTS['stress'])
        result['momentum_neighbor_stress'][str(momentum_days)] = replay['summary']['net_pnl']

    for phase, phase_start in (('wednesday', '2023-01-04'), ('friday', '2023-01-06')):
        phase_targets = weekly_independent_momentum_targets(
            daily, funding, phase_start, END, config, symbol_order=SYMBOLS)
        replay = simulate_trend_portfolio(
            markets, phase_targets, START, END, 500.0, COSTS['stress'])
        result['phase_stress'][phase] = replay['summary']['net_pnl']

    for excluded in SYMBOLS:
        kept = tuple(symbol for symbol in SYMBOLS if symbol != excluded)
        subset_daily = {symbol: daily[symbol] for symbol in kept}
        subset_funding = {symbol: funding[symbol] for symbol in kept}
        subset_targets = weekly_independent_momentum_targets(
            subset_daily, subset_funding, START, END, config, symbol_order=kept)
        replay = simulate_trend_portfolio(
            {symbol: markets[symbol] for symbol in kept}, subset_targets,
            START, END, 500.0, COSTS['stress'])
        result['leave_one_symbol_out_stress'][excluded] = replay['summary']['net_pnl']

    stress, severe = result['continuous_replays']['stress'], result['continuous_replays']['severe']
    dispersion = result['stress_monthly_dispersion']
    slice_pnl = [result['slices'][name]['stress']['net_pnl'] for name in SLICES]
    core_pass = (
        stress['net_pnl'] > 0 and stress['annualized_sharpe'] >= 0.50
        and stress['max_drawdown_pct'] <= 15.0
        and dispersion['positive_month_share'] >= 0.45
        and all(value >= 0 for value in slice_pnl)
        and sum(value > 0 for value in slice_pnl) >= 2
        and dispersion['largest_positive_month_share_of_positive_pnl'] <= 0.60
        and severe['net_pnl'] > 0
        and result['stress_block_bootstrap']['p10_terminal_pnl'] > 0
    )
    risk_neighbor_pass = all(
        row['net_pnl'] > 0 and row['max_drawdown_pct'] <= 15.0
        for row in result['risk_target_neighbor_stress'].values())
    momentum_pass = all(value > 0 for value in result['momentum_neighbor_stress'].values())
    phase_pass = all(value > 0 for value in result['phase_stress'].values())
    loso_pass = sum(value > 0 for value in result['leave_one_symbol_out_stress'].values()) >= 5
    result['gate_components'] = {
        'core_pass': core_pass, 'risk_neighbor_pass': risk_neighbor_pass,
        'momentum_neighbor_pass': momentum_pass, 'phase_pass': phase_pass,
        'leave_one_symbol_out_pass': loso_pass,
    }
    result['decision'] = (
        'HISTORICAL_GATE_PASSED_PAPER_FORWARD_ONLY'
        if all(result['gate_components'].values())
        else 'REJECTED_AT_HISTORICAL_GATE'
    )
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_report(result))


if __name__ == '__main__':
    main()
