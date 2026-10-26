import unittest

import pandas as pd

from l1_filter.funding_carry_scalp import (
    FundingCarryConfig,
    generate_funding_carry_signals,
)


class FundingCarryTests(unittest.TestCase):
    def _bars(self, start):
        index = pd.date_range(start, periods=8, freq='h', tz='UTC')
        return pd.DataFrame({
            'open': 100.0, 'high': 100.4, 'low': 99.6, 'close': 100.0,
            'volume': 50.0, 'taker_buy_volume': 25.0, 'atr1h': 1.0,
            'funding': 0.0004, 'funding_q90': 0.00025, 'funding_q10': -0.00025,
            'pre_settlement': False,
        }, index=index)

    def test_positive_extreme_funding_goes_short_before_settlement(self):
        bars = self._bars('2025-06-01 07:00')
        bars.loc[bars.index[0], 'pre_settlement'] = True
        signals = generate_funding_carry_signals(
            bars, FundingCarryConfig(route='carry_through_settlement'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], -1)

    def test_quiet_funding_does_not_enter(self):
        bars = self._bars('2025-06-02 07:00')
        bars['funding'] = 0.00005
        bars.loc[bars.index[0], 'pre_settlement'] = True
        signals = generate_funding_carry_signals(
            bars, FundingCarryConfig(route='carry_through_settlement'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_negative_extreme_funding_goes_long(self):
        bars = self._bars('2025-06-03 07:00')
        bars['funding'] = -0.0004
        bars.loc[bars.index[0], 'pre_settlement'] = True
        signals = generate_funding_carry_signals(
            bars, FundingCarryConfig(route='carry_and_revert'), 'SOLUSDT')
        self.assertEqual(signals[0]['side'], 1)

    def test_hold_matches_route(self):
        through = FundingCarryConfig(route='carry_through_settlement').execution()
        revert = FundingCarryConfig(route='carry_and_revert').execution()
        self.assertEqual(through.max_hold_minutes, 120)
        self.assertEqual(revert.max_hold_minutes, 480)
        self.assertEqual(through.target_r, 2.5)
        self.assertFalse(through.trailing)
