import unittest

import pandas as pd

from l1_filter.daily_turtle_swing import (
    DailyTurtleConfig,
    generate_daily_turtle_signals,
)


class DailyTurtleSwingTests(unittest.TestCase):
    def _bars(self, start, periods=40):
        index = pd.date_range(start, periods=periods, freq='D', tz='UTC')
        close = pd.Series(100.0, index=index)
        return pd.DataFrame({
            'open': close - 0.3, 'high': close + 0.4, 'low': close - 0.5,
            'close': close, 'volume': 80.0, 'taker_buy_volume': 40.0,
            'atr': 2.0, 'donchian_high': 101.0, 'donchian_low': 98.0,
        }, index=index)

    def test_close_through_prior_20day_high_is_long(self):
        bars = self._bars('2025-05-01')
        bars.loc[bars.index[25], ['open', 'high', 'low', 'close']] = [
            101.0, 104.0, 100.8, 103.2]
        bars.loc[bars.index[25], 'donchian_high'] = 102.0
        signals = generate_daily_turtle_signals(
            bars, DailyTurtleConfig(), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)
        self.assertLess(signals[0]['stop'], signals[0]['reference'])

    def test_inside_channel_does_not_trade(self):
        bars = self._bars('2025-05-02')
        signals = generate_daily_turtle_signals(
            bars, DailyTurtleConfig(), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_payoff_is_uncapped_multi_day_not_two_and_a_half_r(self):
        execution = DailyTurtleConfig().execution()
        self.assertGreaterEqual(execution.target_r, 10.0)
        self.assertFalse(execution.trailing)
        self.assertGreaterEqual(execution.max_hold_minutes, 14 * 1440)
        self.assertEqual(execution.fixed_risk_usd, 10.0)
        self.assertGreaterEqual(execution.drawdown_halt_fraction, 0.20)
