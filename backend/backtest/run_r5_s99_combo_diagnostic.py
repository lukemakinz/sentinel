"""Post-selection same-period diagnostic for R5 cash versus a $250 S99 sleeve."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from l1_filter.independent_dual_momentum import (
    IndependentDualMomentumConfig,
    weekly_independent_momentum_targets,
)
from .book_a_portfolio_sim import simulate_book_a
from .run_s97_dual_horizon_trend import END, SYMBOLS, WARMUP
from .swing_data import load_interval_archives
from .trend_carry_portfolio import TrendPortfolioCosts, simulate_trend_portfolio


START = '2025-05-01'
FIRST_S99_DECISION = '2025-05-05'


def _portfolio_metrics(daily, initial):
    equity = initial + daily.cumsum()
    prior = initial + daily.cumsum().shift(1).fillna(0.0)
    returns = daily / prior
    peak = pd.concat([
        pd.Series([initial], index=[daily.index.min() - pd.Timedelta(days=1)]), equity,
    ]).cummax().iloc[1:]
    drawdown = 1 - equity / peak
    tail_n = max(1, int(np.ceil(len(returns) * .05)))
    days = (daily.index[-1] - daily.index[0]).days + 1
    return {
        'net_pnl': float(daily.sum()),
        'return_pct': float(daily.sum() / initial * 100),
        'max_drawdown_pct': float(drawdown.max() * 100),
        'annualized_sharpe': (
            float(returns.mean() / returns.std(ddof=1) * np.sqrt(365))
            if returns.std(ddof=1) > 0 else 0.0
        ),
        'expected_shortfall_95_daily_return_pct': float(
            returns.nsmallest(tail_n).mean() * 100),
        'usd_per_calendar_day': float(daily.sum() / days),
        'usd_per_average_month': float(daily.sum() / (days / (365.25 / 12))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/r5_s99_combo_diagnostic')
    args = parser.parse_args()
    output = Path(args.output)
    method = output / 'method.json'
    method_hash = sha256(method.read_bytes()).hexdigest()
    (output / 'method.sha256').write_text(f'{method_hash}  method.json\n')

    daily, funding = {}, {}
    for symbol in SYMBOLS:
        daily[symbol], funding[symbol], _ = load_interval_archives(
            symbol, WARMUP, END, args.cache, interval='1d')
    panel = pd.DataFrame({symbol: daily[symbol].close for symbol in SYMBOLS})
    panel.index = panel.index + pd.Timedelta(days=1)
    start, end = pd.Timestamp(START, tz='UTC'), pd.Timestamp(END, tz='UTC')
    with patch('backtest.book_a_portfolio_sim.build_daily_panel', return_value=panel):
        book_a = simulate_book_a(
            {}, replace(BOOK_A_ALT_RM, taker_fee_bps=12.0), start, end,
            250.0, BOOK_A_RISK_DEFAULT)

    config = replace(
        IndependentDualMomentumConfig(), portfolio_vol_target_annual=0.15)
    targets = weekly_independent_momentum_targets(
        daily, funding, FIRST_S99_DECISION, END, config, symbol_order=SYMBOLS)
    s99 = simulate_trend_portfolio(
        {symbol: (daily[symbol], funding[symbol]) for symbol in SYMBOLS},
        targets, start, end, 250.0, TrendPortfolioCosts(8.0, 5.0))

    aligned = pd.concat([
        book_a.daily_pnl.rename('book_a'), s99['daily_pnl'].rename('s99'),
    ], axis=1).fillna(0.0)
    aligned['combo'] = aligned.book_a + aligned.s99
    monthly = aligned.resample('ME').sum()
    official = json.loads(Path('docs/research/book_ab_r5_a_cash/summary.json').read_text())
    official_stress = official['full']['stress']
    official_monthly = official_stress['net_pnl'] / (
        (end - start).days / (365.25 / 12))
    result = {
        'method_sha256': method_hash,
        'window': [str(start), str(end)],
        'book_a_reproduced': _portfolio_metrics(aligned.book_a, 250.0),
        'book_a_official_r5': {
            'net_pnl': official_stress['net_pnl'],
            'max_drawdown_pct_on_total_500': official_stress['max_continuous_drawdown_pct'],
        },
        'book_a_reproduction_pnl_difference': (
            float(aligned.book_a.sum()) - official_stress['net_pnl']),
        's99_250': _portfolio_metrics(aligned.s99, 250.0),
        'r5_cash_baseline_500': {
            'net_pnl': official_stress['net_pnl'],
            'return_pct': official_stress['return_on_slice_start_pct'],
            'max_drawdown_pct': official_stress['max_continuous_drawdown_pct'],
            'usd_per_average_month': official_monthly,
        },
        'book_a_plus_s99_500': _portfolio_metrics(aligned.combo, 500.0),
        'incremental_pnl_vs_official_r5': float(aligned.s99.sum()),
        'daily_pnl_correlation': float(aligned[['book_a', 's99']].corr().iloc[0, 1]),
        'monthly_pnl': {
            str(index): {column: float(value) for column, value in row.items()}
            for index, row in monthly.iterrows()
        },
        'disclosure': 'Post-selection diagnostic; not OOS and not authorization for live trading.',
    }
    (output / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    combo = result['book_a_plus_s99_500']
    s99_metrics = result['s99_250']
    lines = [
        '# R5 + S99 same-period allocation diagnostic', '',
        f'Method hash: `{method_hash}`.', '',
        'Post-selection diagnostic only; the allocation was evaluated after S99 was known.', '',
        '| Portfolio | Capital | Stress PnL | Return | $/month | Max DD |',
        '|---|---:|---:|---:|---:|---:|',
        f'| Official R5: Book A $250 + cash $250 | $500 | '
        f'${official_stress["net_pnl"]:.2f} | {official_stress["return_on_slice_start_pct"]:.2f}% | '
        f'${official_monthly:.2f} | {official_stress["max_continuous_drawdown_pct"]:.2f}% |',
        f'| S99 sleeve alone | $250 | ${s99_metrics["net_pnl"]:.2f} | '
        f'{s99_metrics["return_pct"]:.2f}% | ${s99_metrics["usd_per_average_month"]:.2f} | '
        f'{s99_metrics["max_drawdown_pct"]:.2f}% |',
        f'| Book A $250 + S99 $250 | $500 | ${combo["net_pnl"]:.2f} | '
        f'{combo["return_pct"]:.2f}% | ${combo["usd_per_average_month"]:.2f} | '
        f'{combo["max_drawdown_pct"]:.2f}% |', '',
        f'Daily PnL correlation: **{result["daily_pnl_correlation"]:.3f}**.', '',
        f'The 1d Book A reproduction differs from the official 1m-ledger PnL by '
        f'**${result["book_a_reproduction_pnl_difference"]:.2f}**; official R5 remains the benchmark.', '',
        'Replacing cash with S99 added historical return but also introduced losses in months when R5 was flat. '
        'The allocation needs a fresh paper-forward clock before any promotion.', '',
    ]
    (output / 'REPORT.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
