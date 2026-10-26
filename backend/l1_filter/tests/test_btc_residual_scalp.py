import unittest

import pandas as pd

from l1_filter.btc_residual_scalp import (
    BTCResidualConfig,
    generate_btc_residual_signals,
)


class BTCResidualTests(unittest.TestCase):
    def _bars(self, start, periods=12):
        index = pd.date_range(start, periods=periods, freq='15min', tz='UTC')
        return pd.DataFrame({
            'open': 100.2, 'high': 100.4, 'low': 99.8, 'close': 100.0,
            'volume': 40.0, 'taker_buy_volume': 18.0, 'atr15': 1.0,
            'regime': 0, 'residual_z': 2.4, 'bucket': index.floor('4h'),
        }, index=index)

    def test_alt_rich_vs_btc_fades_short(self):
        bars = self._bars('2025-09-01')
        signals = generate_btc_residual_signals(
            bars, BTCResidualConfig(route='residual_fade'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], -1)

    def test_quiet_residual_does_not_trade(self):
        bars = self._bars('2025-09-02')
        bars['residual_z'] = 0.4
        signals = generate_btc_residual_signals(
            bars, BTCResidualConfig(route='residual_fade'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_sideline_route_skips_uptrend(self):
        bars = self._bars('2025-09-03')
        bars['regime'] = 1
        signals = generate_btc_residual_signals(
            bars, BTCResidualConfig(route='residual_fade_sideline'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_one_trade_per_4h_bucket(self):
        bars = self._bars('2025-09-04', periods=16)
        signals = generate_btc_residual_signals(
            bars, BTCResidualConfig(route='residual_fade'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)

    def test_early_profit_does_not_trail(self):
        execution = BTCResidualConfig().execution()
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.target_r, 1.0)
        self.assertEqual(execution.max_hold_minutes, 90)
