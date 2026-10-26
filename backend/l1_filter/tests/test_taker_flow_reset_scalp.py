import unittest

import pandas as pd

from l1_filter.taker_flow_reset_scalp import (
    TakerFlowResetConfig,
    generate_taker_flow_reset_signals,
)


class TakerFlowResetTests(unittest.TestCase):
    def _bars(self, start, periods=16):
        index = pd.date_range(start, periods=periods, freq='15min', tz='UTC')
        return pd.DataFrame({
            'open': 100.0, 'high': 100.4, 'low': 99.6, 'close': 100.1,
            'volume': 40.0, 'taker_buy_volume': 22.0, 'atr': 1.0,
            'regime': 1, 'taker_ratio': 0.55, 'prior_high': 100.5,
            'prior_low': 99.4, 'bucket': index.floor('4h'),
        }, index=index)

    def test_flush_then_recovery_break_is_long_in_uptrend(self):
        bars = self._bars('2025-07-01')
        bars.loc[bars.index[4], ['taker_ratio', 'taker_buy_volume', 'close', 'high']] = [
            0.32, 12.0, 99.9, 100.1]
        bars.loc[bars.index[6], ['taker_ratio', 'taker_buy_volume', 'close', 'high']] = [
            0.62, 30.0, 101.2, 101.4]
        signals = generate_taker_flow_reset_signals(
            bars, TakerFlowResetConfig(route='flow_reset_15m'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)

    def test_sideline_skips(self):
        bars = self._bars('2025-07-02')
        bars['regime'] = 0
        bars.loc[bars.index[4], 'taker_ratio'] = 0.32
        bars.loc[bars.index[6], ['taker_ratio', 'close', 'high']] = [0.62, 101.2, 101.4]
        signals = generate_taker_flow_reset_signals(
            bars, TakerFlowResetConfig(route='flow_reset_15m'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_payoff_is_two_and_a_half_r(self):
        fifteen = TakerFlowResetConfig(route='flow_reset_15m').execution()
        five = TakerFlowResetConfig(route='flow_reset_5m').execution()
        self.assertEqual(fifteen.target_r, 2.5)
        self.assertFalse(fifteen.trailing)
        self.assertEqual(fifteen.max_hold_minutes, 240)
        self.assertEqual(five.max_hold_minutes, 90)
        self.assertEqual(five.minutes, 5)
