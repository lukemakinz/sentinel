import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from l1_filter.h1_trend_pullback import (
    H1TrendPullbackConfig,
    generate_h1_signals,
)


def synthetic_features(hour=10):
    index = pd.date_range(
        f'2026-01-05 {hour:02d}:00', periods=4, freq='15min', tz='UTC',
    )
    frame = pd.DataFrame({
        'open': [99.0, 100.2, 100.0, 100.4],
        'high': [101.0, 100.8, 100.7, 100.8],
        'low': [99.0, 100.0, 100.0, 100.2],
        'close': [100.8, 100.6, 100.6, 100.5],
        'volume': [200.0] * 4,
        'atr': [1.0] * 4,
        'prior_high': [100.0] * 4,
        'prior_low': [98.0] * 4,
        'h1_long': [True] * 4,
        'h1_short': [False] * 4,
        'h4_long': [True] * 4,
        'h4_short': [False] * 4,
        'h1_adx': [25.0] * 4,
        'h4_adx': [23.0] * 4,
        'long_displacement': [True, False, False, False],
        'short_displacement': [False] * 4,
        'five_long_confirm': [False, True, False, False],
        'five_short_confirm': [False] * 4,
    }, index=index)
    return frame


class H1TrendPullbackTest(SimpleTestCase):
    def test_first_confirmed_retest_emits_one_limit_candidate(self):
        signals = generate_h1_signals(
            synthetic_features(), H1TrendPullbackConfig(), 'TESTUSDT',
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)
        self.assertAlmostEqual(signals[0]['limit_price'], 100.1)
        self.assertAlmostEqual(signals[0]['stop'], 98.85)
        self.assertEqual(signals[0]['limit_ttl_minutes'], 30)

    def test_session_filter_rejects_late_confirmation(self):
        self.assertEqual(generate_h1_signals(
            synthetic_features(hour=20), H1TrendPullbackConfig(), 'TESTUSDT',
        ), [])

    def test_too_tight_structural_stop_is_rejected(self):
        frame = synthetic_features()
        frame.loc[frame.index[0], 'low'] = 99.8
        self.assertEqual(generate_h1_signals(
            frame, H1TrendPullbackConfig(), 'TESTUSDT',
        ), [])

    def test_later_data_does_not_change_existing_signal(self):
        base = synthetic_features()
        first = generate_h1_signals(base, H1TrendPullbackConfig(), 'TESTUSDT')
        future = base.copy()
        future.loc[future.index[-1], ['open', 'high', 'low', 'close']] = np.array(
            [50.0, 55.0, 45.0, 48.0],
        )
        second = generate_h1_signals(future, H1TrendPullbackConfig(), 'TESTUSDT')
        self.assertEqual(first[0]['setup_id'], second[0]['setup_id'])

    def test_v2_uses_confirmation_body_midpoint_without_chasing(self):
        config = H1TrendPullbackConfig(
            name='H1_TREND_PULLBACK_CONFIRM_V2',
            entry_mode='confirmation_body_midpoint',
        )
        frame = synthetic_features()
        frame.loc[frame.index[0], 'low'] = 99.3
        signal = generate_h1_signals(
            frame, config, 'TESTUSDT',
        )[0]
        self.assertAlmostEqual(signal['limit_price'], 100.4)
        self.assertEqual(signal['evidence']['entry_mode'], 'confirmation_body_midpoint')
