import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from l1_filter.h3_double_sweep_divergence import (
    H3DoubleSweepConfig,
    _confirmed_pivots,
    generate_h3_signals,
)


def bullish_double_bottom():
    index = pd.date_range('2026-01-05 06:00', periods=30, freq='15min', tz='UTC')
    frame = pd.DataFrame({
        'open': np.full(30, 100.5),
        'high': np.full(30, 100.8),
        'low': np.full(30, 100.4),
        'close': np.full(30, 100.5),
        'atr': np.ones(30),
        'rsi': np.full(30, 50.0),
        'h1_adx': np.full(30, 20.0),
        'h4_adx': np.full(30, 22.0),
    }, index=index)
    frame.loc[index[10], ['open', 'high', 'low', 'close', 'rsi']] = [100.4, 100.6, 100.0, 100.3, 25.0]
    frame.loc[index[20], ['open', 'high', 'low', 'close', 'rsi']] = [100.1, 100.4, 99.7, 100.2, 32.0]
    # At index 22 the second pivot becomes known and the neckline breaks.
    frame.loc[index[22], ['open', 'high', 'low', 'close']] = [100.5, 101.0, 100.4, 100.9]
    return frame


class H3DoubleSweepTest(SimpleTestCase):
    def test_pivot_is_published_only_after_right_hand_confirmation(self):
        values = np.array([2.0, 1.0, 2.0, 3.0])
        self.assertEqual(_confirmed_pivots(values, 1, lows=True), [(1, 2)])

    def test_bullish_double_bottom_divergence_breaks_and_retests(self):
        signals = generate_h3_signals(
            bullish_double_bottom(), H3DoubleSweepConfig(), 'TESTUSDT',
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)
        self.assertAlmostEqual(signals[0]['limit_price'], 100.8)
        self.assertAlmostEqual(signals[0]['stop'], 99.55)
        self.assertEqual(signals[0]['evidence']['rsi_divergence'], 7.0)

    def test_strong_trend_regime_rejects_reversal(self):
        frame = bullish_double_bottom()
        frame['h1_adx'] = 35.0
        self.assertEqual(generate_h3_signals(
            frame, H3DoubleSweepConfig(), 'TESTUSDT',
        ), [])

    def test_future_mutation_does_not_change_published_signal(self):
        frame = bullish_double_bottom()
        first = generate_h3_signals(frame, H3DoubleSweepConfig(), 'TESTUSDT')
        frame.loc[frame.index[-1], ['open', 'high', 'low', 'close']] = [50, 55, 45, 48]
        second = generate_h3_signals(frame, H3DoubleSweepConfig(), 'TESTUSDT')
        self.assertEqual(first[0]['setup_id'], second[0]['setup_id'])
