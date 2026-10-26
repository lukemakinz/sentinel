import unittest

import pandas as pd

from l1_filter.donchian_4h_scalp import (
    Donchian4hConfig,
    generate_donchian_4h_signals,
)


class Donchian4hTests(unittest.TestCase):
    def _bars(self, start, periods=30):
        index = pd.date_range(start, periods=periods, freq='4h', tz='UTC')
        close = pd.Series(100.0, index=index)
        return pd.DataFrame({
            'open': close - 0.2, 'high': close + 0.4, 'low': close - 0.5,
            'close': close, 'volume': 80.0, 'taker_buy_volume': 40.0,
            'atr': 1.5, 'donchian_high': 101.0, 'donchian_low': 98.0,
            'session_day': index.normalize(),
        }, index=index)

    def test_close_through_prior_channel_high_is_long(self):
        bars = self._bars('2025-05-01')
        bars.loc[bars.index[20], ['open', 'high', 'low', 'close']] = [
            101.0, 103.0, 100.8, 102.6]
        bars.loc[bars.index[20], 'donchian_high'] = 102.0
        signals = generate_donchian_4h_signals(
            bars, Donchian4hConfig(route='donchian_20'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)

    def test_inside_channel_does_not_trade(self):
        bars = self._bars('2025-05-02')
        bars['close'] = 100.0
        bars['high'] = 100.5
        bars['donchian_high'] = 102.0
        bars['donchian_low'] = 98.0
        signals = generate_donchian_4h_signals(
            bars, Donchian4hConfig(route='donchian_20'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_one_signal_per_day(self):
        bars = self._bars('2025-05-03')
        for ts in bars.index[18:22]:
            bars.loc[ts, ['high', 'close']] = [103.0, 102.8]
            bars.loc[ts, 'donchian_high'] = 102.0
        signals = generate_donchian_4h_signals(
            bars, Donchian4hConfig(route='donchian_20'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)

    def test_payoff_is_two_and_a_half_r_not_one_r(self):
        execution = Donchian4hConfig(route='donchian_20').execution()
        self.assertEqual(execution.target_r, 2.5)
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.max_hold_minutes, 2160)
        self.assertEqual(Donchian4hConfig(route='donchian_10').execution().max_hold_minutes, 1440)
