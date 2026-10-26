import unittest

import pandas as pd

from l1_filter.prior_day_breakout import (
    PriorDayBreakoutConfig,
    generate_prior_day_breakout_signals,
)


class PriorDayBreakoutTests(unittest.TestCase):
    def _bars(self, start, periods=40):
        index = pd.date_range(start, periods=periods, freq='5min', tz='UTC')
        return pd.DataFrame({
            'open': 100.0, 'high': 100.2, 'low': 99.8, 'close': 100.0,
            'volume': 20.0, 'taker_buy_volume': 12.0, 'atr': 1.0,
            'regime': 1, 'prev_high': 100.5, 'prev_low': 99.2,
            'prev_range': 1.3, 'in_entry_window': True,
            'session_day': index.normalize(),
        }, index=index)

    def test_close_through_prior_day_high_is_long(self):
        bars = self._bars('2025-06-02 01:00')
        bars.loc[bars.index[3], ['high', 'close']] = [101.0, 100.9]
        signals = generate_prior_day_breakout_signals(
            bars, PriorDayBreakoutConfig(), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)

    def test_sideline_does_not_trade(self):
        bars = self._bars('2025-06-03 01:00')
        bars['regime'] = 0
        bars.loc[bars.index[3], ['high', 'close']] = [101.0, 100.9]
        signals = generate_prior_day_breakout_signals(
            bars, PriorDayBreakoutConfig(), 'XRPUSDT')
        self.assertEqual(signals, [])

    def test_second_break_same_day_is_ignored(self):
        bars = self._bars('2025-06-04 01:00')
        bars.loc[bars.index[3], ['high', 'close']] = [101.0, 100.9]
        bars.loc[bars.index[8], ['high', 'close']] = [101.4, 101.3]
        signals = generate_prior_day_breakout_signals(
            bars, PriorDayBreakoutConfig(), 'SOLUSDT')
        self.assertEqual(len(signals), 1)

    def test_hold_to_close_is_not_a_one_r_scalp(self):
        execution = PriorDayBreakoutConfig().execution()
        self.assertGreaterEqual(execution.target_r, 6.0)
        self.assertFalse(execution.trailing)
        self.assertGreaterEqual(execution.max_hold_minutes, 12 * 60)
        self.assertEqual(execution.fixed_risk_usd, 10.0)
