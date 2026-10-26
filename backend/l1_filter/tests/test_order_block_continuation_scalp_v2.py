import numpy as np
import pandas as pd
import unittest

from l1_filter.order_block_continuation_scalp import order_block_features
from l1_filter.order_block_continuation_scalp_v2 import (
    OrderBlockRejectionConfig,
    generate_order_block_rejection_signals,
)


def _manual_bars(rows: list[dict]) -> pd.DataFrame:
    index = pd.date_range('2026-01-01', periods=len(rows), freq='15min', tz='UTC')
    frame = pd.DataFrame(rows, index=index)
    defaults = {
        'atr': 1.0, 'htf_trend_up': False, 'htf_trend_down': False, 'htf_adx': 25.0,
        'obv': 1.0, 'obv_ema': 0.0, 'ob_bull_confirmed': False, 'ob_bull_top': np.nan,
        'ob_bull_bottom': np.nan, 'ob_bear_confirmed': False, 'ob_bear_top': np.nan,
        'ob_bear_bottom': np.nan,
    }
    for column, value in defaults.items():
        if column not in frame.columns:
            frame[column] = value
    return frame


def _trending_minutes(periods=60 * 24 * 90, seed=0):
    rng = np.random.default_rng(seed)
    index = pd.date_range('2025-01-01', periods=periods, freq='min', tz='UTC')
    drift = np.linspace(0, 60, periods)
    noise = np.cumsum(rng.normal(0, 0.06, periods))
    bursts = np.zeros(periods)
    burst_starts = rng.integers(0, periods - 20, size=periods // 2000)
    for start in burst_starts:
        bursts[start:start + 5] += rng.choice([-1, 1]) * np.linspace(0, 3, 5)
    close = 100 + drift + noise + bursts
    high = close + np.abs(rng.normal(0.05, 0.02, periods))
    low = close - np.abs(rng.normal(0.05, 0.02, periods))
    open_ = close + rng.normal(0, 0.02, periods)
    volume = rng.uniform(5, 15, periods)
    volume[bursts != 0] *= 3
    taker = volume * rng.uniform(0.4, 0.6, periods)
    return pd.DataFrame({'open': open_, 'high': high, 'low': low, 'close': close,
                         'volume': volume, 'taker_buy_volume': taker}, index=index)


class OrderBlockRejectionZoneStateTests(unittest.TestCase):
    def test_zone_survives_a_weak_touch_then_fires_on_a_rejection_candle(self):
        bars = _manual_bars([
            {'open': 99.0, 'high': 100.5, 'low': 98.8, 'close': 99.5,
             'ob_bull_confirmed': True, 'ob_bull_top': 100.0, 'ob_bull_bottom': 98.0,
             'htf_trend_up': True},
            {'open': 99.3, 'high': 99.6, 'low': 99.0, 'close': 99.2,  # weak doji-ish touch
             'htf_trend_up': True},
            {'open': 101.0, 'high': 101.5, 'low': 100.8, 'close': 101.2,  # no touch
             'htf_trend_up': True},
            {'open': 98.6, 'high': 100.0, 'low': 98.5, 'close': 99.8,  # genuine rejection
             'htf_trend_up': True},
        ])
        config = OrderBlockRejectionConfig('test', 'base')
        signals = generate_order_block_rejection_signals(bars, config, 'ETHUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['timestamp'], bars.index[3])
        self.assertEqual(signals[0]['side'], 1)

    def test_zone_is_invalidated_by_a_clean_close_through_it_no_signal(self):
        bars = _manual_bars([
            {'open': 99.0, 'high': 100.5, 'low': 98.8, 'close': 99.5,
             'ob_bull_confirmed': True, 'ob_bull_top': 100.0, 'ob_bull_bottom': 98.0,
             'htf_trend_up': True},
            {'open': 98.5, 'high': 98.9, 'low': 97.0, 'close': 97.2,  # closes clean below bottom
             'htf_trend_up': True},
            {'open': 98.6, 'high': 100.0, 'low': 98.5, 'close': 99.8,  # would-be rejection, but zone is gone
             'htf_trend_up': True},
        ])
        config = OrderBlockRejectionConfig('test', 'base')
        signals = generate_order_block_rejection_signals(bars, config, 'ETHUSDT')
        self.assertEqual(signals, [])

    def test_rejection_without_regime_confirmation_consumes_zone_without_signal(self):
        bars = _manual_bars([
            {'open': 99.0, 'high': 100.5, 'low': 98.8, 'close': 99.5,
             'ob_bull_confirmed': True, 'ob_bull_top': 100.0, 'ob_bull_bottom': 98.0,
             'htf_trend_up': False},  # regime never confirms
            {'open': 98.6, 'high': 100.0, 'low': 98.5, 'close': 99.8,
             'htf_trend_up': False},
        ])
        config = OrderBlockRejectionConfig('test', 'base')
        signals = generate_order_block_rejection_signals(bars, config, 'ETHUSDT')
        self.assertEqual(signals, [])


class OrderBlockRejectionInvariantTests(unittest.TestCase):
    def test_divergence_signals_are_a_subset_of_base_signals(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=1)
        base_config = OrderBlockRejectionConfig('base', 'base')
        divergence_config = OrderBlockRejectionConfig('divergence', 'divergence')
        bars = order_block_features(minutes, base_config)
        base_signals = generate_order_block_rejection_signals(bars, base_config, 'ETHUSDT')
        divergence_signals = generate_order_block_rejection_signals(bars, divergence_config, 'ETHUSDT')
        base_keys = {(s['timestamp'], s['side']) for s in base_signals}
        divergence_keys = {(s['timestamp'], s['side']) for s in divergence_signals}
        self.assertTrue(divergence_keys.issubset(base_keys))

    def test_no_conflicting_directions_at_same_timestamp(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=2)
        config = OrderBlockRejectionConfig('base', 'base')
        bars = order_block_features(minutes, config)
        signals = generate_order_block_rejection_signals(bars, config, 'ETHUSDT')
        timestamps = [s['timestamp'] for s in signals]
        self.assertEqual(len(timestamps), len(set(timestamps)))

    def test_signals_require_positive_risk_and_finite_atr(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=3)
        config = OrderBlockRejectionConfig('base', 'base')
        bars = order_block_features(minutes, config)
        signals = generate_order_block_rejection_signals(bars, config, 'ETHUSDT')
        self.assertGreater(len(signals), 0)
        for signal in signals:
            risk = signal['side'] * (signal['reference'] - signal['stop'])
            self.assertGreater(risk, 0)
            self.assertTrue(np.isfinite(signal['atr']))

    def test_fewer_or_equal_signals_than_v1_same_bars(self):
        # The rejection filter can only make entries more selective than the
        # plain first-touch v1 trigger on identical bars/config semantics.
        from l1_filter.order_block_continuation_scalp import (
            OrderBlockContinuationConfig, generate_order_block_signals,
        )
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=4)
        v1_config = OrderBlockContinuationConfig('v1', 'base')
        v2_config = OrderBlockRejectionConfig('v2', 'base')
        bars = order_block_features(minutes, v1_config)
        v1_signals = generate_order_block_signals(bars, v1_config, 'ETHUSDT')
        v2_signals = generate_order_block_rejection_signals(bars, v2_config, 'ETHUSDT')
        self.assertLessEqual(len(v2_signals), len(v1_signals))

    def test_route_validation_rejects_unknown_route(self):
        with self.assertRaises(ValueError):
            OrderBlockRejectionConfig('bad', 'reversal')
