import unittest

import pandas as pd

from l1_filter.fresh_level_sweep_reclaim import _latest_eligible_by_bar
from l1_filter.intraday_level_reclaim import btc_sma200_regime_filter


class IntradayLevelReclaimTests(unittest.TestCase):
    def test_linear_latest_swing_lookup_matches_frozen_definition(self):
        swings = [(2, 4, 10.0), (7, 9, 12.0), (12, 14, 11.0)]
        actual = _latest_eligible_by_bar(swings, 20, lookback=6)
        expected = []
        for known in range(20):
            eligible = [
                item for item in swings
                if max(0, known - 6) <= item[0] < known and item[1] < known
            ]
            expected.append(max(eligible, key=lambda item: item[0]) if eligible else None)
        self.assertEqual(actual, expected)

    def test_btc_regime_uses_only_completed_daily_bars(self):
        index = pd.date_range('2025-01-01', periods=205 * 1440, freq='1min', tz='UTC')
        frame = pd.DataFrame({
            'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.0,
            'volume': 1.0, 'taker_buy_volume': 0.5,
        }, index=index)
        # The day before publication turns risk-on.  A future crash after the
        # signal must not change the already-published decision.
        created = index[202 * 1440]
        frame.loc[(frame.index >= created - pd.Timedelta(days=1))
                  & (frame.index < created), 'close'] = 120.0
        frame.loc[frame.index >= created, 'close'] = 50.0
        levels = [
            {'created_at': created, 'side': 1, 'evidence': {}, 'setup_id': 'long'},
            {'created_at': created, 'side': -1, 'evidence': {}, 'setup_id': 'short'},
        ]
        selected = btc_sma200_regime_filter(levels, frame)
        self.assertEqual([item['setup_id'] for item in selected], ['long'])


if __name__ == '__main__':
    unittest.main()
