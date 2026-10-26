import unittest

import pandas as pd

from l1_filter.rsi2_mean_reversion import (
    Rsi2Config,
    generate_rsi2_signals,
)


class Rsi2MeanReversionTests(unittest.TestCase):
    def _bars(self, start, periods=30):
        index = pd.date_range(start, periods=periods, freq='D', tz='UTC')
        close = pd.Series(100.0, index=index)
        return pd.DataFrame({
            'open': close - 0.2, 'high': close + 0.3, 'low': close - 0.4,
            'close': close, 'volume': 80.0, 'taker_buy_volume': 40.0,
            'atr': 2.0, 'rsi2': 50.0, 'sma20': 99.0,
        }, index=index)

    def test_oversold_above_sma_is_long(self):
        bars = self._bars('2025-05-01')
        bars.loc[bars.index[21], 'rsi2'] = 8.0
        bars.loc[bars.index[21], 'close'] = 100.5
        signals = generate_rsi2_signals(bars, Rsi2Config(), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)

    def test_oversold_below_sma_does_not_buy(self):
        bars = self._bars('2025-05-02')
        bars['sma20'] = 101.0
        bars.loc[bars.index[21], 'rsi2'] = 8.0
        bars.loc[bars.index[21], 'close'] = 100.0
        signals = generate_rsi2_signals(bars, Rsi2Config(), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_payoff_is_short_hold_mean_reversion_not_turtle(self):
        execution = Rsi2Config().execution()
        self.assertEqual(execution.target_r, 3.0)
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.max_hold_minutes, 5 * 1440)
        self.assertEqual(execution.fixed_risk_usd, 10.0)
