import unittest

import pandas as pd

from l1_filter.bollinger_mean_revert import (
    BollingerMeanRevertConfig,
    generate_bollinger_mean_revert_signals,
)


class BollingerMeanRevertTests(unittest.TestCase):
    def _bars(self, start, periods=12):
        index = pd.date_range(start, periods=periods, freq='4h', tz='UTC')
        close = pd.Series(100.0, index=index)
        return pd.DataFrame({
            'open': close - 0.2, 'high': close + 0.3, 'low': close - 0.4,
            'close': close, 'volume': 40.0, 'taker_buy_volume': 20.0,
            'atr': 1.5, 'adx': 18.0, 'bb_upper': 103.0, 'bb_mid': 100.0,
            'bb_lower': 97.0, 'session_day': index.normalize(),
        }, index=index)

    def test_close_below_lower_band_in_chop_is_long_to_the_mid(self):
        bars = self._bars('2025-06-02')
        bars.loc[bars.index[4], 'close'] = 96.5
        signals = generate_bollinger_mean_revert_signals(
            bars, BollingerMeanRevertConfig(), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)
        self.assertAlmostEqual(signals[0]['target_price'], 100.0)

    def test_trending_band_touch_does_not_fade(self):
        bars = self._bars('2025-06-03')
        bars['adx'] = 40.0
        bars.loc[bars.index[4], 'close'] = 96.5
        signals = generate_bollinger_mean_revert_signals(
            bars, BollingerMeanRevertConfig(), 'XRPUSDT')
        self.assertEqual(signals, [])

    def test_execution_targets_the_mean_on_two_slots(self):
        execution = BollingerMeanRevertConfig().execution()
        self.assertEqual(execution.max_positions, 2)
        self.assertEqual(execution.fixed_risk_usd, 15.0)
        self.assertEqual(execution.max_hold_minutes, 1440)
