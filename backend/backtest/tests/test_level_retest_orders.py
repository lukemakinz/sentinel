import unittest

import pandas as pd

from backtest.level_retest_orders import materialize_first_retests


class MaterializeLevelRetestTests(unittest.TestCase):
    def test_first_future_touch_preserves_arm_time(self):
        index = pd.date_range('2026-01-01', periods=4, freq='1min', tz='UTC')
        minutes = pd.DataFrame({
            'open': [105, 104, 102, 101],
            'high': [106, 105, 103, 102],
            'low': [104, 103, 99, 98],
            'close': [105, 104, 100, 99],
        }, index=index)
        signal = {
            'timestamp': index[0], 'side': 1, 'limit_price': 100.0,
            'limit_ttl_minutes': 4, 'evidence': {'armed_before_retest': True},
        }
        result = materialize_first_retests(minutes, [signal], penetration_bps=2)
        self.assertEqual(result[0]['timestamp'], index[2])
        self.assertEqual(result[0]['evidence']['armed_at'], str(index[0]))
        self.assertEqual(result[0]['limit_ttl_minutes'], 1)

    def test_gap_through_limit_is_not_invented_from_ohlc(self):
        index = pd.date_range('2026-01-01', periods=2, freq='1min', tz='UTC')
        minutes = pd.DataFrame({
            'open': [105, 98], 'high': [106, 99],
            'low': [104, 95], 'close': [105, 96],
        }, index=index)
        signal = {
            'timestamp': index[0], 'side': 1, 'limit_price': 100.0,
            'limit_ttl_minutes': 2,
        }
        self.assertEqual(materialize_first_retests(minutes, [signal]), [])


if __name__ == '__main__':
    unittest.main()
