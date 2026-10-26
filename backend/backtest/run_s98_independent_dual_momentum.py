"""Frozen continuous replay for S98 independent dual momentum."""
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
    COSTS,
    END,
    SLICES,
    START,
    SYMBOLS,
    WARMUP,
    _block_bootstrap,
    _monthly_dispersion,
    _slice_metrics,
)
from .swing_data import load_interval_archives
from .trend_carry_portfolio import simulate_trend_portfolio


PROTOCOL_SHA256 = 'fa1a9933a09ed58045a9c60218be2d9ba038a4cd73299ec290db4e50286f8af1'


def _render_report(result):
    lines = [
        '# S98 — independent dual momentum', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        'All periods are contaminated historical diagnostics, not true OOS.', '',
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
        f'- Momentum neighbors, stress PnL: `{result["neighbor_stress_pnl"]}`.',
        f'- Rebalance phases, stress PnL: `{result["phase_stress_pnl"]}`.',
        f'- Leave-one-symbol-out, stress PnL: `{result["leave_one_symbol_out_stress_pnl"]}`.',
        f'- 28-day block bootstrap: `{result["stress_block_bootstrap"]}`.',
        '', f'**Decision: {result["decision"]}.**', '',
        'A pass authorizes paper-forward observation only; it is not proof of future profit.', '',
    ])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s98_independent_dual_momentum')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(f'Protocol changed after freeze: expected {PROTOCOL_SHA256}, got {actual_hash}')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    daily, funding, manifest = {}, {}, {}
    for symbol in SYMBOLS:
        daily[symbol], funding[symbol], manifest[symbol] = load_interval_archives(
            symbol, WARMUP, END, args.cache, interval='1d')
        print(symbol, len(daily[symbol]), 'verified daily candles', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    markets = {symbol: (daily[symbol], funding[symbol]) for symbol in SYMBOLS}

    config = IndependentDualMomentumConfig()
    targets = weekly_independent_momentum_targets(
        daily, funding, START, END, config, symbol_order=SYMBOLS)
    result = {
        'protocol_sha256': actual_hash,
        'config': asdict(config),
        'weekly_decisions': len(targets),
        'invested_decisions': sum(bool(target['weights']) for target in targets),
        'continuous_replays': {}, 'slices': {},
        'neighbor_stress_pnl': {}, 'phase_stress_pnl': {},
        'leave_one_symbol_out_stress_pnl': {},
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

    for momentum_days in (63, 126):
        neighbor = replace(config, momentum_days=momentum_days)
        neighbor_targets = weekly_independent_momentum_targets(
            daily, funding, START, END, neighbor, symbol_order=SYMBOLS)
        replay = simulate_trend_portfolio(
            markets, neighbor_targets, START, END, 500.0, COSTS['stress'])
        result['neighbor_stress_pnl'][str(momentum_days)] = replay['summary']['net_pnl']

    for phase, phase_start in (
        ('wednesday', '2023-01-04'), ('friday', '2023-01-06')):
        phase_targets = weekly_independent_momentum_targets(
            daily, funding, phase_start, END, config, symbol_order=SYMBOLS)
        replay = simulate_trend_portfolio(
            markets, phase_targets, START, END, 500.0, COSTS['stress'])
        result['phase_stress_pnl'][phase] = replay['summary']['net_pnl']

    for excluded in SYMBOLS:
        kept = tuple(symbol for symbol in SYMBOLS if symbol != excluded)
        subset_daily = {symbol: daily[symbol] for symbol in kept}
        subset_funding = {symbol: funding[symbol] for symbol in kept}
        subset_targets = weekly_independent_momentum_targets(
            subset_daily, subset_funding, START, END, config, symbol_order=kept)
        replay = simulate_trend_portfolio(
            {symbol: markets[symbol] for symbol in kept}, subset_targets,
            START, END, 500.0, COSTS['stress'])
        result['leave_one_symbol_out_stress_pnl'][excluded] = replay['summary']['net_pnl']

    stress = result['continuous_replays']['stress']
    severe = result['continuous_replays']['severe']
    dispersion = result['stress_monthly_dispersion']
    slice_values = [result['slices'][name]['stress']['net_pnl'] for name in SLICES]
    core_pass = (
        stress['net_pnl'] > 0 and stress['annualized_sharpe'] >= 0.50
        and stress['max_drawdown_pct'] <= 15.0
        and dispersion['positive_month_share'] >= 0.45
        and all(value >= 0 for value in slice_values)
        and sum(value > 0 for value in slice_values) >= 2
        and dispersion['largest_positive_month_share_of_positive_pnl'] <= 0.60
        and severe['net_pnl'] > 0
    )
    neighbor_pass = all(value > 0 for value in result['neighbor_stress_pnl'].values())
    phase_pass = all(value > 0 for value in result['phase_stress_pnl'].values())
    loso_pass = sum(
        value > 0 for value in result['leave_one_symbol_out_stress_pnl'].values()
    ) >= 5
    result['gate_components'] = {
        'core_pass': core_pass, 'neighbor_pass': neighbor_pass,
        'phase_pass': phase_pass, 'leave_one_symbol_out_pass': loso_pass,
    }
    result['decision'] = (
        'HISTORICAL_GATE_PASSED_PAPER_FORWARD_ONLY'
        if core_pass and neighbor_pass and phase_pass and loso_pass
        else 'REJECTED_AT_HISTORICAL_GATE'
    )
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(result))


if __name__ == '__main__':
    main()
