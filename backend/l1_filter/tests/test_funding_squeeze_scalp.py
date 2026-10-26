import unittest

import pandas as pd

from l1_filter.funding_squeeze_scalp import (
    FundingSqueezeConfig,
    generate_funding_squeeze_signals,
)


class FundingSqueezeTests(unittest.TestCase):
    def _bars(self, start, periods=12):
        index = pd.date_range(start, periods=periods, freq='15min', tz='UTC')
        return pd.DataFrame({
            'open': 100.2, 'high': 100.4, 'low': 99.8, 'close': 100.0,
            'volume': 50.0, 'taker_buy_volume': 20.0, 'atr15': 1.0,
            'regime': 0, 'funding': 0.0004, 'funding_q90': 0.0003,
            'funding_q10': -0.0003, 'funding_time': index[0],
        }, index=index)

    def test_crowded_positive_funding_fades_short_on_rejection(self):
        bars = self._bars('2025-07-01')
        signals = generate_funding_squeeze_signals(
            bars, FundingSqueezeConfig(route='crowded_fade'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], -1)

    def test_quiet_funding_does_not_trade(self):
        bars = self._bars('2025-07-02')
        bars['funding'] = 0.0001
        bars['funding_q90'] = 0.0003
        signals = generate_funding_squeeze_signals(
            bars, FundingSqueezeConfig(route='crowded_fade'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_sideline_route_skips_uptrend(self):
        bars = self._bars('2025-07-03')
        bars['regime'] = 1
        signals = generate_funding_squeeze_signals(
            bars, FundingSqueezeConfig(route='crowded_fade_sideline'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_one_trade_per_funding_settlement(self):
        bars = self._bars('2025-07-04', periods=8)
        signals = generate_funding_squeeze_signals(
            bars, FundingSqueezeConfig(route='crowded_fade'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)

    def test_early_profit_does_not_trail(self):
        execution = FundingSqueezeConfig().execution()
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.target_r, 1.0)
        self.assertEqual(execution.max_hold_minutes, 120)
