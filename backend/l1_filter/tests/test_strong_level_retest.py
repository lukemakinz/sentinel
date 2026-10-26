from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from l1_filter.strong_level_retest import (
    StrongLevelRetestConfig,
    confirmed_swings,
    level_strength_score,
    prepare_four_hour_bars,
    strong_level_events_from_bars,
)


def synthetic_bars():
    index = pd.date_range('2025-01-01 04:00', periods=217, freq='4h', tz='UTC')
    close = 100 + np.arange(217) * 0.09 + np.sin(np.arange(217) * np.pi / 3) * 0.35
    frame = pd.DataFrame({
        'open': close - 0.08,
        'high': close + 0.45,
        'low': close - 0.45,
        'close': close,
        'volume': 100.0,
        'taker_buy_volume': 50.0,
    }, index=index)
    pattern = [
        (119.8, 120.3, 119.4, 120.0),
        (120.0, 120.2, 118.7, 119.1),
        (119.1, 119.4, 118.10, 118.7),
        (118.7, 119.8, 118.5, 119.5),
        (119.5, 120.8, 119.3, 120.5),
        (120.5, 120.7, 119.1, 119.4),
        (119.4, 119.6, 118.7, 118.9),
        (118.9, 119.4, 118.6, 119.0),
        (119.0, 119.3, 118.20, 118.7),
        (118.7, 119.9, 118.5, 119.6),
        (119.6, 120.7, 119.4, 120.4),
        (120.4, 121.40, 120.2, 121.0),
        (121.0, 121.1, 119.9, 120.3),
        (120.3, 120.5, 119.6, 119.8),
        (119.30, 119.50, 118.50, 118.80),
        (118.80, 121.80, 118.70, 121.50),
        (121.50, 122.70, 121.30, 122.40),
    ]
    for i, values in enumerate(pattern, start=200):
        frame.iloc[i, frame.columns.get_indexer(['open', 'high', 'low', 'close'])] = values
    frame.loc[index[215], 'volume'] = 240.0
    frame.loc[index[216], 'volume'] = 180.0
    return prepare_four_hour_bars(frame)


class StrongLevelRetestTests(unittest.TestCase):
    def test_score_rewards_sr_confluence_and_trend(self):
        weak, _ = level_strength_score(
            displacement_ratio=1.3, volume_ratio=1.3, prior_touches=2,
            trend_aligned=False, zone_width_ratio=0.5)
        strong, parts = level_strength_score(
            displacement_ratio=2.0, volume_ratio=1.8, prior_touches=4,
            trend_aligned=True, zone_width_ratio=0.5)
        self.assertGreater(strong, weak)
        self.assertEqual(parts['sr_confluence'], 20.0)
        self.assertLessEqual(strong, 100.0)

    def test_swing_is_published_two_bars_after_pivot(self):
        frame = pd.DataFrame({
            'high': [1, 2, 5, 2, 1],
            'low': [0, -1, -2, -1, 0],
        })
        highs, lows = confirmed_swings(frame, width=2)
        self.assertIn((2, 4, 5.0), highs)
        self.assertIn((2, 4, -2.0), lows)

    def test_event_is_prearmed_and_prefix_invariant(self):
        bars = synthetic_bars()
        config = replace(
            StrongLevelRetestConfig(),
            min_score=60.0,
            cluster_atr=0.70,
        )
        prefix_events = strong_level_events_from_bars(bars, config)
        self.assertTrue(prefix_events)
        event = prefix_events[-1]
        # The displacement candle itself confirms the setup.  Publication is
        # at that candle's close, never at the earlier OB or swing timestamp.
        self.assertEqual(event['created_at'], bars.index[-2])
        self.assertLess(event['entry'], bars.loc[event['created_at'], 'close'])
        self.assertGreaterEqual(event['prior_touches'], 2)

        future = bars.iloc[-1:].copy()
        future.index = [bars.index[-1] + pd.Timedelta(hours=4)]
        future[['open', 'high', 'low', 'close']] = 90.0
        appended = pd.concat([bars, future])
        later_events = strong_level_events_from_bars(appended, config)
        original = [x for x in later_events if x['created_at'] <= bars.index[-1]]
        self.assertEqual(prefix_events, original)


if __name__ == '__main__':
    unittest.main()
