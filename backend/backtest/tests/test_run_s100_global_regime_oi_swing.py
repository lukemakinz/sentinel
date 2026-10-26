import unittest

import pandas as pd

from backtest.run_s100_global_regime_oi_swing import _daily_open_interest


class DailyOpenInterestTests(unittest.TestCase):
    def test_uses_last_fresh_positive_snapshot_without_future_fill(self):
        index = pd.to_datetime([
            '2025-01-01 23:50:00Z', '2025-01-01 23:55:00Z',
            '2025-01-02 23:50:00Z', '2025-01-02 23:55:00Z',
        ])
        metrics = pd.DataFrame({
            'open_interest': [100.0, 0.0, 110.0, 120.0],
            'metrics_age_minutes': [0.0, 0.0, 0.0, 15.0],
        }, index=index)
        result = _daily_open_interest(metrics)
        self.assertEqual(result.tolist(), [100.0, 110.0])


if __name__ == '__main__':
    unittest.main()
