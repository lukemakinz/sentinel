import unittest

import pandas as pd

from l1_filter.trend_displacement_scalp import (
    TrendDisplacementConfig,
    generate_trend_displacement_signals,
)


class TrendDisplacementTests(unittest.TestCase):
    def _bars(self, start, periods=20, freq='5min'):
        index = pd.date_range(start, periods=periods, freq=freq, tz='UTC')
        close = pd.Series(100.0, index=index)
        return pd.DataFrame({
            'open': close - 0.1, 'high': close + 0.2, 'low': close - 0.2,
            'close': close, 'volume': 20.0, 'taker_buy_volume': 10.0,
            'atr': 1.0, 'regime': 1, 'prior_high': 100.3, 'prior_low': 99.7,
            'volume_median': 10.0, 'bucket': index.floor('4h'),
        }, index=index)

    def test_uptrend_displacement_emits_one_long(self):
        bars = self._bars('2025-08-01')
        bars.loc[bars.index[5], ['open', 'high', 'low', 'close', 'volume']] = [
            100.2, 102.0, 100.1, 101.8, 40.0]
        signals = generate_trend_displacement_signals(
            bars, TrendDisplacementConfig(route='displacement_5m'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)

    def test_sideline_is_skipped(self):
        bars = self._bars('2025-08-02')
        bars['regime'] = 0
        bars.loc[bars.index[5], ['open', 'high', 'low', 'close', 'volume']] = [
            100.2, 102.0, 100.1, 101.8, 40.0]
        signals = generate_trend_displacement_signals(
            bars, TrendDisplacementConfig(route='displacement_5m'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_second_displacement_same_4h_is_ignored(self):
        bars = self._bars('2025-08-03')
        bars.loc[bars.index[4], ['open', 'high', 'low', 'close', 'volume']] = [
            100.2, 102.0, 100.1, 101.8, 40.0]
        bars.loc[bars.index[8], ['open', 'high', 'low', 'close', 'volume']] = [
            101.8, 103.5, 101.7, 103.2, 40.0]
        signals = generate_trend_displacement_signals(
            bars, TrendDisplacementConfig(route='displacement_5m'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)

    def test_early_profit_does_not_trail(self):
        five = TrendDisplacementConfig(route='displacement_5m').execution()
        fifteen = TrendDisplacementConfig(route='displacement_15m').execution()
        self.assertFalse(five.trailing)
        self.assertEqual(five.target_r, 1.0)
        self.assertEqual(five.max_hold_minutes, 45)
        self.assertEqual(fifteen.max_hold_minutes, 90)
        self.assertEqual(fifteen.minutes, 15)
