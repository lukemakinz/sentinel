import unittest

import numpy as np
import pandas as pd

from l1_filter.global_regime_trend_oi import (
    AsymmetricRegimeConfig, asymmetric_global_regimes,
)
from l1_filter.tests.test_global_direction_oi import _daily


class AsymmetricRegimeTests(unittest.TestCase):
    def test_broad_trends_map_to_both_directions(self):
        up = np.linspace(100, 300, 280)
        down = np.linspace(300, 100, 280)
        config = AsymmetricRegimeConfig(confirmation_days=1)
        up_daily = {symbol: _daily(up * scale) for symbol, scale in (
            ('BTCUSDT', 1.0), ('ETHUSDT', 0.5), ('SOLUSDT', 0.1))}
        down_daily = {symbol: _daily(down * scale) for symbol, scale in (
            ('BTCUSDT', 1.0), ('ETHUSDT', 0.5), ('SOLUSDT', 0.1))}
        decision = '2024-10-06'
        self.assertEqual(asymmetric_global_regimes(
            up_daily, decision, '2024-10-07', config).regime.iloc[0], 'UP')
        self.assertEqual(asymmetric_global_regimes(
            down_daily, decision, '2024-10-07', config).regime.iloc[0], 'DOWN')


if __name__ == '__main__':
    unittest.main()
