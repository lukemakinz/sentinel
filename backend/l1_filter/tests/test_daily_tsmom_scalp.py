import unittest

import pandas as pd

from l1_filter.daily_tsmom_scalp import (
    DailyTSMOMConfig,
    generate_daily_tsmom_signals,
)


class DailyTSMOMTests(unittest.TestCase):
    def _bars(self, start, periods=40):
        index = pd.date_range(start, periods=periods, freq='D', tz='UTC')
        close = 100.0 + pd.Series(range(periods), index=index).astype(float)
        return pd.DataFrame({
            'open': close - 0.5, 'high': close + 1.0, 'low': close - 1.0,
            'close': close, 'volume': 100.0, 'taker_buy_volume': 50.0,
            'atr': 2.0, 'mom': close - close.shift(20),
        }, index=index)

    def test_positive_momentum_emits_long(self):
        bars = self._bars('2025-05-01')
        signals = generate_daily_tsmom_signals(
            bars, DailyTSMOMConfig(route='tsmom_20'), 'SOLUSDT')
        longs = [s for s in signals if s['side'] == 1]
        self.assertGreater(len(longs), 0)

    def test_flat_momentum_does_not_trade(self):
        bars = self._bars('2025-06-01')
        bars['mom'] = 0.0
        bars['close'] = 100.0
        signals = generate_daily_tsmom_signals(
            bars, DailyTSMOMConfig(route='tsmom_20'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_payoff_is_two_and_a_half_r(self):
        twenty = DailyTSMOMConfig(route='tsmom_20').execution()
        ten = DailyTSMOMConfig(route='tsmom_10').execution()
        self.assertEqual(twenty.target_r, 2.5)
        self.assertFalse(twenty.trailing)
        self.assertEqual(twenty.max_hold_minutes, 7200)
        self.assertEqual(ten.max_hold_minutes, 4320)
