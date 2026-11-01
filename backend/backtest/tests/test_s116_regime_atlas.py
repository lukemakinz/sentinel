import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from backtest.run_s116_regime_atlas import (
    apply_brake, btc_sma200_stream, classify_regimes, router_map,
)


def closes(values, start='2022-01-01'):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq='D', tz='UTC'))


class RegimeTest(SimpleTestCase):
    def test_regime_is_causal_and_classifies_trend(self):
        rng = np.random.default_rng(1)
        up = closes(100 * np.exp(np.cumsum(0.003 + rng.normal(0, 0.01, 600))))
        regimes = classify_regimes(up)
        self.assertEqual(regimes.trend.dropna().iloc[-1], 'UP')
        # Changing the last close must not change the last day's regime.
        tweaked = up.copy()
        tweaked.iloc[-1] = tweaked.iloc[-1] * 0.5
        self.assertEqual(classify_regimes(tweaked).cell.iloc[-1], regimes.cell.iloc[-1])

    def test_router_requires_size_mean_t_and_every_year(self):
        good = {'2023': 0.4, '2024': 0.6}
        dev = {'BOOK_A': {'UP_LOW': {'n': 150, 'mean': 0.5, 't': 3.1, 'year_means': good},
                          'UP_HIGH': {'n': 80, 'mean': 0.9, 't': 4.0, 'year_means': good},
                          'DOWN_LOW': {'n': 150, 'mean': 0.1, 't': 2.0, 'year_means': good},
                          'DOWN_HIGH': {'n': 150, 'mean': 0.5, 't': 3.5,
                                        'year_means': {'2023': 1.2, '2024': -0.1}}},
               'S115_A': {'DOWN_HIGH': {'n': 60, 'mean': 0.2, 't': 3.0, 'year_means': good}}}
        self.assertEqual(router_map(dev), {'BOOK_A': ['UP_LOW'], 'S115_A': ['DOWN_HIGH']})

    def test_concurrency_cap_skips_new_trades_while_full(self):
        from backtest.run_s116_regime_atlas import cap_concurrency
        t = pd.DataFrame({
            'entry_time': pd.to_datetime(['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-20'], utc=True),
            'exit_time': pd.to_datetime(['2025-01-15', '2025-01-16', '2025-01-17', '2025-01-30'], utc=True),
        })
        kept = cap_concurrency(t, 2)
        self.assertEqual(list(kept.index), [0, 1, 3])

    def test_brake_halves_after_ten_percent_drawdown(self):
        daily = closes([-60.0, 10.0, 10.0])  # -60 on the $500 portfolio = 12% drawdown
        braked = apply_brake(daily)
        self.assertEqual(list(braked), [-60.0, 5.0, 5.0])

    def test_sma_stream_enters_next_day_only(self):
        values = [100.0] * 200 + [110.0, 121.0]
        bars = pd.DataFrame({'close': values}, index=closes(values).index)
        pnl = btc_sma200_stream(bars, pd.Series(dtype=float, index=pd.DatetimeIndex([], tz='UTC')),
                                cost_bps=0)
        # Day 200 closes above SMA200 -> exposure only from day 201.
        self.assertEqual(pnl.iloc[200], 0.0)
        self.assertAlmostEqual(pnl.iloc[201], 250 * 0.1)
