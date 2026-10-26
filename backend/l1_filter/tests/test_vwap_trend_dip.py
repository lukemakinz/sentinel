import unittest

import pandas as pd

from l1_filter.vwap_trend_dip import (
    VwapTrendDipConfig,
    generate_vwap_trend_dip_signals,
)


class VwapTrendDipTests(unittest.TestCase):
    def _bars(self, start, periods=20):
        index = pd.date_range(start, periods=periods, freq='15min', tz='UTC')
        close = pd.Series(100.0, index=index)
        close.iloc[4] = 99.2
        close.iloc[5] = 100.4
        return pd.DataFrame({
            'open': close - 0.1, 'high': close + 0.2, 'low': close - 0.3,
            'close': close, 'volume': 50.0, 'taker_buy_volume': 25.0,
            'atr': 1.0, 'vwap': 100.0, 'regime': 1, 'in_entry_window': True,
            'session_day': index.normalize(),
        }, index=index)

    def test_reclaim_of_vwap_in_uptrend_is_long(self):
        bars = self._bars('2025-06-02 01:00')
        signals = generate_vwap_trend_dip_signals(
            bars, VwapTrendDipConfig(), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)

    def test_sideline_does_not_trade(self):
        bars = self._bars('2025-06-03 01:00')
        bars['regime'] = 0
        signals = generate_vwap_trend_dip_signals(
            bars, VwapTrendDipConfig(), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_hold_is_session_not_one_r_scalp(self):
        execution = VwapTrendDipConfig().execution()
        self.assertGreaterEqual(execution.target_r, 6.0)
        self.assertFalse(execution.trailing)
        self.assertGreaterEqual(execution.max_hold_minutes, 10 * 60)
        self.assertEqual(execution.fixed_risk_usd, 10.0)
