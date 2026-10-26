"""Ablation: does S102's global regime gate + ETH short add value over plain S99?

Both books replayed from the S102 execution start with $500 and identical costs.
"""
from dataclasses import replace

import numpy as np
import pandas as pd

from l1_filter.global_regime_trend_oi import (
    AsymmetricRegimeConfig, RegimeTrendOIConfig,
    asymmetric_global_regimes, weekly_regime_trend_oi_targets,
)
from l1_filter.independent_dual_momentum import (
    IndependentDualMomentumConfig, weekly_independent_momentum_targets,
)
from .metrics_data import load_metrics
from .run_s100_global_regime_oi_swing import _daily_open_interest
from .run_s101_asymmetric_regime_trend_oi import (
    COSTS, END, OI_SYMBOLS, OI_WARMUP, PRICE_WARMUP, START, SYMBOLS,
)
from .swing_data import load_interval_archives
from .trend_carry_portfolio import simulate_trend_portfolio

CACHE = '/tmp/sentinel-s97-cache'
SLICES = {
    '2024-08..2024-12': ('2024-08-01', '2025-01-01'),
    '2025': ('2025-01-01', '2026-01-01'),
    '2026-01..2026-08': ('2026-01-01', '2026-09-01'),
}


def _stats(daily_pnl, capital=500.0):
    nav = capital + daily_pnl.cumsum()
    returns = daily_pnl / nav.shift(1).fillna(capital)
    sharpe = returns.mean() / returns.std() * np.sqrt(365) if returns.std() else 0.0
    dd = ((nav.cummax() - nav) / nav.cummax()).max() * 100
    days = len(daily_pnl)
    pnl = daily_pnl.sum()
    return {
        'pnl': round(pnl, 2), 'usd_day_500': round(pnl / days, 3),
        'usd_day_250': round(pnl / days / 2, 3), 'max_dd_pct': round(dd, 2),
        'sharpe': round(sharpe, 2),
        'exposure_days_pct': round((daily_pnl != 0).mean() * 100, 1),
    }


def main():
    daily, funding = {}, {}
    for symbol in SYMBOLS:
        daily[symbol], funding[symbol], _ = load_interval_archives(
            symbol, PRICE_WARMUP, END, CACHE, interval='1d')
    oi = {}
    for symbol in OI_SYMBOLS:
        metrics, _ = load_metrics(symbol, OI_WARMUP, END, CACHE,
                                  include_freshness=True,
                                  required_columns=('open_interest',))
        oi[symbol] = _daily_open_interest(metrics)
    markets = {s: (daily[s], funding[s]) for s in SYMBOLS}

    regimes = asymmetric_global_regimes(daily, START, END, AsymmetricRegimeConfig())
    variants = {
        'S99_ungated_15vol': weekly_independent_momentum_targets(
            daily, funding, START, END,
            replace(IndependentDualMomentumConfig(), portfolio_vol_target_annual=0.15),
            symbol_order=SYMBOLS),
        'S102_gated_long_short': weekly_regime_trend_oi_targets(
            daily, funding, oi, regimes, START, END, RegimeTrendOIConfig(),
            symbol_order=SYMBOLS, short_symbols=('ETHUSDT',)),
        'S102_gated_long_only': weekly_regime_trend_oi_targets(
            daily, funding, oi, regimes, START, END, RegimeTrendOIConfig(),
            symbol_order=SYMBOLS, short_symbols=()),
    }
    rows = []
    for name, targets in variants.items():
        replay = simulate_trend_portfolio(markets, targets, START, END, 500.0, COSTS['stress'])
        pnl = replay['daily_pnl']
        row = {'variant': name, **_stats(pnl)}
        for label, (a, b) in SLICES.items():
            row[label] = round(pnl[(pnl.index >= a) & (pnl.index < b)].sum(), 2)
        rows.append(row)
    table = pd.DataFrame(rows).set_index('variant')
    with pd.option_context('display.width', 250, 'display.max_columns', 20):
        print(table)


if __name__ == '__main__':
    main()
