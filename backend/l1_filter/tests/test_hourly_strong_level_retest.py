from unittest.mock import patch
import unittest

import pandas as pd

from l1_filter.hourly_strong_level_retest import (
    HourlyStrongLevelRetestConfig,
    hourly_strong_level_signals,
)


class HourlyStrongLevelRetestTests(unittest.TestCase):
    @patch('l1_filter.hourly_strong_level_retest.strong_level_events_from_bars')
    @patch('l1_filter.hourly_strong_level_retest.hourly_level_features')
    def test_order_is_armed_at_confirmation_not_after_touch(self, features, events):
        timestamp = pd.Timestamp('2026-01-02 12:00', tz='UTC')
        features.return_value = pd.DataFrame({'close': [110.0]}, index=[timestamp])
        events.return_value = [{
            'created_at': timestamp,
            'side': 1,
            'stop': 98.0,
            'atr4h': 4.0,
            'entry': 100.0,
            'target': 106.0,
            'score': 82.0,
            'setup_id': 'test',
            'bottom': 99.0,
            'top': 101.0,
            'score_components': {'sr_confluence': 15.0},
            'prior_touches': 3,
            'displacement_atr': 2.0,
            'volume_ratio': 1.5,
            'trend_aligned': True,
        }]
        config = HourlyStrongLevelRetestConfig()
        _, signals = hourly_strong_level_signals(pd.DataFrame(), config)
        self.assertEqual(signals[0]['timestamp'], timestamp)
        self.assertEqual(signals[0]['limit_price'], 100.0)
        self.assertEqual(signals[0]['limit_ttl_minutes'], 36 * 60)
        self.assertTrue(signals[0]['evidence']['armed_before_retest'])


if __name__ == '__main__':
    unittest.main()
