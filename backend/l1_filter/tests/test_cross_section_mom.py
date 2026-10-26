import unittest

import pandas as pd

from l1_filter.cross_section_mom import (
    CrossSectionMomConfig,
    generate_cross_section_signals,
)


class CrossSectionMomTests(unittest.TestCase):
    def _bars(self, start, mom, periods=8):
        index = pd.date_range(start, periods=periods, freq='D', tz='UTC')
        close = pd.Series(100.0, index=index)
        return pd.DataFrame({
            'open': close - 0.2, 'high': close + 0.3, 'low': close - 0.4,
            'close': close, 'volume': 80.0, 'taker_buy_volume': 40.0,
            'atr': 2.0, 'mom': mom,
        }, index=index)

    def test_stronger_leg_is_long_weaker_is_short(self):
        index_start = '2025-06-10'
        sol = self._bars(index_start, 0.20)
        xrp = self._bars(index_start, 0.04)
        signals = generate_cross_section_signals(
            {'SOLUSDT': sol, 'XRPUSDT': xrp}, CrossSectionMomConfig())
        self.assertEqual(signals['SOLUSDT'][0]['side'], 1)
        self.assertEqual(signals['XRPUSDT'][0]['side'], -1)
        self.assertEqual(signals['SOLUSDT'][0]['timestamp'], signals['XRPUSDT'][0]['timestamp'])

    def test_tiny_spread_does_not_trade(self):
        sol = self._bars('2025-06-11', 0.10)
        xrp = self._bars('2025-06-11', 0.09)
        signals = generate_cross_section_signals(
            {'SOLUSDT': sol, 'XRPUSDT': xrp}, CrossSectionMomConfig())
        self.assertEqual(signals['SOLUSDT'], [])
        self.assertEqual(signals['XRPUSDT'], [])

    def test_execution_is_dual_slot_one_day_hold(self):
        execution = CrossSectionMomConfig().execution()
        self.assertEqual(execution.max_positions, 2)
        self.assertEqual(execution.fixed_risk_usd, 15.0)
        self.assertEqual(execution.max_hold_minutes, 1440)
