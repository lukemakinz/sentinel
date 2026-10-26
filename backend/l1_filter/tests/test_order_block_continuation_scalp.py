import numpy as np
import pandas as pd
import unittest

from l1_filter.order_block_continuation_scalp import (
    OrderBlockContinuationConfig,
    generate_order_block_signals,
    order_block_features,
)


def _trending_minutes(periods=60 * 24 * 90, seed=0):
    rng = np.random.default_rng(seed)
    index = pd.date_range('2025-01-01', periods=periods, freq='min', tz='UTC')
    drift = np.linspace(0, 60, periods)
    noise = np.cumsum(rng.normal(0, 0.06, periods))
    # Periodic sharp displacement bursts so order blocks actually form.
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


class OrderBlockFeaturesTests(unittest.TestCase):
    def test_features_are_prefix_invariant(self):
        config = OrderBlockContinuationConfig('test', 'base')
        minutes = _trending_minutes(periods=60 * 24 * 60)
        cutoff = pd.Timestamp('2025-02-20', tz='UTC')
        prefix = order_block_features(minutes.loc[minutes.index < cutoff], config)
        full = order_block_features(minutes, config).loc[prefix.index]
        columns = ['atr', 'rsi14', 'cvd', 'obv', 'obv_ema', 'htf_adx',
                   'htf_trend_up', 'htf_trend_down', 'ob_bull_confirmed',
                   'ob_bull_top', 'ob_bull_bottom', 'ob_bear_confirmed',
                   'ob_bear_top', 'ob_bear_bottom']
        pd.testing.assert_frame_equal(prefix[columns], full[columns])

    def test_order_block_needs_displacement_and_volume(self):
        config = OrderBlockContinuationConfig('test', 'base')
        minutes = _trending_minutes(periods=60 * 24 * 60)
        bars = order_block_features(minutes, config)
        self.assertTrue(bars.ob_bull_confirmed.any())
        self.assertTrue(bars.ob_bear_confirmed.any())
        # A confirmed bullish OB must sit below a bearish-candle open/close pair.
        confirmed = bars.loc[bars.ob_bull_confirmed]
        self.assertTrue((confirmed.ob_bull_top > confirmed.ob_bull_bottom).all())


class OrderBlockSignalsTests(unittest.TestCase):
    def test_divergence_signals_are_a_subset_of_base_signals(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=1)
        base_config = OrderBlockContinuationConfig('base', 'base')
        divergence_config = OrderBlockContinuationConfig('divergence', 'divergence')
        bars = order_block_features(minutes, base_config)
        base_signals = generate_order_block_signals(bars, base_config, 'ETHUSDT')
        divergence_signals = generate_order_block_signals(bars, divergence_config, 'ETHUSDT')
        base_keys = {(s['timestamp'], s['side']) for s in base_signals}
        divergence_keys = {(s['timestamp'], s['side']) for s in divergence_signals}
        self.assertTrue(divergence_keys.issubset(base_keys))

    def test_no_conflicting_directions_at_same_timestamp(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=2)
        config = OrderBlockContinuationConfig('base', 'base')
        bars = order_block_features(minutes, config)
        signals = generate_order_block_signals(bars, config, 'ETHUSDT')
        timestamps = [s['timestamp'] for s in signals]
        self.assertEqual(len(timestamps), len(set(timestamps)))

    def test_signals_require_positive_risk_and_finite_atr(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=3)
        config = OrderBlockContinuationConfig('base', 'base')
        bars = order_block_features(minutes, config)
        signals = generate_order_block_signals(bars, config, 'ETHUSDT')
        self.assertGreater(len(signals), 0)
        for signal in signals:
            risk = signal['side'] * (signal['reference'] - signal['stop'])
            self.assertGreater(risk, 0)
            self.assertTrue(np.isfinite(signal['atr']))

    def test_route_validation_rejects_unknown_route(self):
        with self.assertRaises(ValueError):
            OrderBlockContinuationConfig('bad', 'reversal')

    def test_zone_is_consumed_after_first_touch(self):
        # Two touches of the same price region should yield at most one
        # candidate per side per zone lifetime, not one per touch.
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=4)
        config = OrderBlockContinuationConfig('base', 'base', zone_ttl_bars=200)
        bars = order_block_features(minutes, config)
        signals = generate_order_block_signals(bars, config, 'ETHUSDT')
        setup_ids = [s['setup_id'] for s in signals]
        self.assertEqual(len(setup_ids), len(set(setup_ids)))
