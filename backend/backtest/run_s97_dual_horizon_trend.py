"""Frozen continuous replay for S97 dual-horizon trend."""
import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.dual_horizon_trend import (
    DualHorizonTrendConfig,
    weekly_dual_horizon_targets,
)
from .swing_data import load_interval_archives
from .trend_carry_portfolio import TrendPortfolioCosts, simulate_trend_portfolio


PROTOCOL_SHA256 = 'b260e0dceeba431112c1d4a5213390fc0028f714fe7cee3962f3d697220c9bc9'
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT')
WARMUP, START, END = '2022-04-04', '2023-01-02', '2026-09-01'
SLICES = {
    'development': ('2023-01-02', '2024-01-01'),
    'validation': ('2024-01-01', '2025-01-06'),
    'retrospective_evaluation': ('2025-01-06', END),
}
COSTS = {
    'base': TrendPortfolioCosts(5.0, 2.0),
    'stress': TrendPortfolioCosts(8.0, 5.0),
    'severe': TrendPortfolioCosts(10.0, 10.0),
}


def _utc(value):
    value = pd.Timestamp(value)
    return value.tz_localize('UTC') if value.tzinfo is None else value.tz_convert('UTC')


def _slice_metrics(daily: pd.Series, start, end, initial=500.0) -> dict:
    start, end = _utc(start), _utc(end)
    selected = daily.loc[(daily.index >= start) & (daily.index < end)]
    before = daily.loc[daily.index < start]
    start_nav = initial + float(before.sum())
    full_equity = initial + daily.cumsum()
    running_peak = pd.concat([
        pd.Series([initial], index=[daily.index.min() - pd.Timedelta(days=1)]),
        full_equity,
    ]).cummax().iloc[1:]
    selected_equity = full_equity.reindex(selected.index)
    drawdown = 1 - selected_equity / running_peak.reindex(selected.index)
    prior_equity = (initial + daily.cumsum().shift(1).fillna(0.0)).reindex(selected.index)
    returns = selected / prior_equity
    return {
        'start_nav': start_nav,
        'net_pnl': float(selected.sum()),
        'return_on_start_nav_pct': float(selected.sum() / start_nav * 100),
        'usd_per_calendar_day': float(selected.sum() / max(1, (end - start).days)),
        'max_continuous_drawdown_pct': float(drawdown.max() * 100) if len(drawdown) else 0.0,
        'annualized_sharpe': (
            float(returns.mean() / returns.std(ddof=1) * np.sqrt(365))
            if len(returns) > 1 and returns.std(ddof=1) > 0 else 0.0
        ),
        'positive_month_share': float((selected.resample('ME').sum() > 0).mean()),
    }


def _monthly_dispersion(daily: pd.Series) -> dict:
    monthly = daily.resample('ME').sum()
    positives = monthly[monthly > 0]
    total_positive = float(positives.sum())
    return {
        'months': len(monthly),
        'positive_months': int((monthly > 0).sum()),
        'positive_month_share': float((monthly > 0).mean()),
        'largest_positive_month_share_of_positive_pnl': (
            float(positives.max() / total_positive) if total_positive > 0 else 1.0
        ),
        'best_month_pnl': float(monthly.max()),
        'worst_month_pnl': float(monthly.min()),
        'monthly_pnl': {str(index): float(value) for index, value in monthly.items()},
    }


def _block_bootstrap(daily: pd.Series, initial=500.0, block=28, samples=5000) -> dict:
    equity = initial + daily.cumsum()
    prior = initial + daily.cumsum().shift(1).fillna(0.0)
    returns = (daily / prior).to_numpy(dtype=float)
    rng = np.random.default_rng(9701)
    n = len(returns)
    terminals = np.empty(samples, dtype=float)
    offsets = np.arange(block)
    for sample in range(samples):
        starts = rng.integers(0, n, size=int(np.ceil(n / block)))
        indices = np.concatenate([(start + offsets) % n for start in starts])[:n]
        terminals[sample] = initial * np.prod(1 + returns[indices]) - initial
    return {
        'method': 'circular_28d_blocks',
        'samples': samples,
        'p10_terminal_pnl': float(np.quantile(terminals, 0.10)),
        'p50_terminal_pnl': float(np.quantile(terminals, 0.50)),
        'p90_terminal_pnl': float(np.quantile(terminals, 0.90)),
        'observed_terminal_pnl': float(equity.iloc[-1] - initial),
    }


def _render_report(result: dict) -> str:
    lines = [
        '# S97 — dual-horizon trend with funding-crowding veto', '',
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
    lines.extend(['', '## Frozen robustness checks', '',
                  f'- Neighbor horizons, stress PnL: `{result["neighbor_stress_pnl"]}`.',
                  f'- Leave-one-symbol-out, stress PnL: `{result["leave_one_symbol_out_stress_pnl"]}`.',
                  f'- 28-day block bootstrap: `{result["stress_block_bootstrap"]}`.',
                  '', f'**Decision: {result["decision"]}.**', '',
                  'A historical pass authorizes only prospective paper-forward observation; live trading remains disabled.', ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s97_dual_horizon_trend')
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

    config = DualHorizonTrendConfig()
    targets = weekly_dual_horizon_targets(
        daily, funding, START, END, config, symbol_order=SYMBOLS)
    result = {
        'protocol_sha256': actual_hash,
        'config': asdict(config),
        'weekly_decisions': int((pd.date_range(START, END, freq='7D', inclusive='left')).size),
        'targets': len(targets),
        'continuous_replays': {},
        'slices': {},
        'neighbor_stress_pnl': {},
        'leave_one_symbol_out_stress_pnl': {},
    }
    replays = {}
    for scenario, scenario_costs in COSTS.items():
        replay = simulate_trend_portfolio(
            markets, targets, START, END, 500.0, scenario_costs)
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

    for fast, slow in ((21, 84), (35, 140)):
        neighbor = replace(config, fast_days=fast, slow_days=slow)
        neighbor_targets = weekly_dual_horizon_targets(
            daily, funding, START, END, neighbor, symbol_order=SYMBOLS)
        replay = simulate_trend_portfolio(
            markets, neighbor_targets, START, END, 500.0, COSTS['stress'])
        result['neighbor_stress_pnl'][f'{fast}_{slow}'] = replay['summary']['net_pnl']

    for excluded in SYMBOLS:
        kept = tuple(symbol for symbol in SYMBOLS if symbol != excluded)
        subset_daily = {symbol: daily[symbol] for symbol in kept}
        subset_funding = {symbol: funding[symbol] for symbol in kept}
        subset_targets = weekly_dual_horizon_targets(
            subset_daily, subset_funding, START, END, config, symbol_order=kept)
        replay = simulate_trend_portfolio(
            {symbol: markets[symbol] for symbol in kept}, subset_targets,
            START, END, 500.0, COSTS['stress'])
        result['leave_one_symbol_out_stress_pnl'][excluded] = replay['summary']['net_pnl']

    stress = result['continuous_replays']['stress']
    severe = result['continuous_replays']['severe']
    dispersion = result['stress_monthly_dispersion']
    slices = result['slices']
    core_pass = (
        stress['net_pnl'] > 0
        and stress['annualized_sharpe'] >= 0.50
        and stress['max_drawdown_pct'] <= 15.0
        and dispersion['positive_month_share'] >= 0.45
        and slices['development']['stress']['net_pnl'] > 0
        and slices['validation']['stress']['net_pnl'] > 0
        and slices['retrospective_evaluation']['stress']['net_pnl'] >= 0
        and dispersion['largest_positive_month_share_of_positive_pnl'] <= 0.60
        and severe['net_pnl'] > 0
    )
    neighbor_pass = all(value > 0 for value in result['neighbor_stress_pnl'].values())
    loso_pass = sum(
        value > 0 for value in result['leave_one_symbol_out_stress_pnl'].values()
    ) >= 5
    result['gate_components'] = {
        'core_pass': core_pass,
        'neighbor_pass': neighbor_pass,
        'leave_one_symbol_out_pass': loso_pass,
    }
    result['decision'] = (
        'HISTORICAL_GATE_PASSED_PAPER_FORWARD_ONLY'
        if core_pass and neighbor_pass and loso_pass
        else 'REJECTED_AT_HISTORICAL_GATE'
    )
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(result))


if __name__ == '__main__':
    main()
