import unittest

import pandas as pd

from l1_filter.spread_zscore_fade import (
    SpreadZscoreConfig,
    generate_spread_zscore_signals,
)


class SpreadZscoreFadeTests(unittest.TestCase):
    def _bars(self, start, z, periods=5):
        index = pd.date_range(start, periods=periods, freq='D', tz='UTC')
        close = pd.Series(100.0, index=index)
        return pd.DataFrame({
            'open': close - 0.2, 'high': close + 0.4, 'low': close - 0.5,
            'close': close, 'volume': 80.0, 'taker_buy_volume': 40.0,
            'atr': 2.0, 'z': z,
        }, index=index)

    def test_rich_sol_is_short_sol_and_long_xrp(self):
        sol = self._bars('2025-06-10', 2.4)
        xrp = self._bars('2025-06-10', 2.4)
        signals = generate_spread_zscore_signals(
            {'SOLUSDT': sol, 'XRPUSDT': xrp}, SpreadZscoreConfig())
        self.assertEqual(signals['SOLUSDT'][0]['side'], -1)
        self.assertEqual(signals['XRPUSDT'][0]['side'], 1)

    def test_quiet_spread_does_not_trade(self):
        sol = self._bars('2025-06-11', 0.4)
        xrp = self._bars('2025-06-11', 0.4)
        signals = generate_spread_zscore_signals(
            {'SOLUSDT': sol, 'XRPUSDT': xrp}, SpreadZscoreConfig())
        self.assertEqual(signals['SOLUSDT'], [])
        self.assertEqual(signals['XRPUSDT'], [])

    def test_hold_is_three_days_on_two_slots(self):
        execution = SpreadZscoreConfig().execution()
        self.assertEqual(execution.max_positions, 2)
        self.assertEqual(execution.fixed_risk_usd, 15.0)
        self.assertEqual(execution.max_hold_minutes, 3 * 1440)
