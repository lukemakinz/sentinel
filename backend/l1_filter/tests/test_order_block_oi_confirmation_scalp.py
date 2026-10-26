import numpy as np
import pandas as pd
import unittest

from l1_filter.order_block_continuation_scalp import OrderBlockContinuationConfig
from l1_filter.order_block_oi_confirmation_scalp import (
    OrderBlockOIConfig,
    generate_order_block_oi_signals,
    oi_features,
)


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


def _synthetic_metrics(minutes: pd.DataFrame, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range(minutes.index[0], minutes.index[-1] + pd.Timedelta(minutes=1),
                          freq='5min', inclusive='left')
    oi = 1_000_000 + np.cumsum(rng.normal(0, 500, len(index)))
    toptrader = 1.5 + np.cumsum(rng.normal(0, 0.002, len(index)))
    return pd.DataFrame({
        'open_interest': oi,
        'open_interest_value': oi * 2000,
        'toptrader_account_ratio': toptrader,
        'toptrader_position_ratio': toptrader,
        'retail_account_ratio': toptrader,
        'taker_buy_sell_vol_ratio': np.abs(rng.normal(1.0, 0.3, len(index))),
    }, index=index)


class OrderBlockOIFeaturesTests(unittest.TestCase):
    def test_features_are_prefix_invariant(self):
        config = OrderBlockOIConfig('test', 'oi')
        minutes = _trending_minutes(periods=60 * 24 * 60)
        # One master metrics frame, sliced for both calls, so any mismatch is
        # attributable to oi_features itself rather than the RNG fixture.
        master_metrics = _synthetic_metrics(minutes)
        cutoff = pd.Timestamp('2025-02-20', tz='UTC')
        prefix = oi_features(minutes.loc[minutes.index < cutoff],
                             master_metrics.loc[master_metrics.index < cutoff], config)
        full = oi_features(minutes, master_metrics, config).loc[prefix.index]
        columns = ['open_interest', 'toptrader_position_ratio', 'oi_change', 'toptrader_zscore']
        # Drop the single boundary bar: resample_closed's last 15m label can
        # legitimately equal `cutoff` even though its minutes are all < cutoff,
        # while the metrics slice excludes a same-instant 5m row by strict <
        # — a test-fixture edge effect, not a causality issue in oi_features.
        pd.testing.assert_frame_equal(prefix[columns].iloc[:-1], full[columns].iloc[:-1])

    def test_oi_change_matches_manual_difference(self):
        config = OrderBlockOIConfig('test', 'oi', oi_lookback_bars=2)
        minutes = _trending_minutes(periods=60 * 24 * 5)
        metrics = _synthetic_metrics(minutes)
        bars = oi_features(minutes, metrics, config)
        expected = bars.open_interest.iloc[10] - bars.open_interest.iloc[8]
        self.assertAlmostEqual(bars.oi_change.iloc[10], expected, places=6)


class OrderBlockOISignalsTests(unittest.TestCase):
    def test_toptrader_route_is_a_subset_of_oi_base_route(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=1)
        metrics = _synthetic_metrics(minutes, seed=1)
        base_config = OrderBlockOIConfig('base', 'oi')
        tt_config = OrderBlockOIConfig('tt', 'oi_toptrader')
        bars = oi_features(minutes, metrics, base_config)
        base_signals = generate_order_block_oi_signals(bars, base_config, 'ETHUSDT')
        tt_signals = generate_order_block_oi_signals(bars, tt_config, 'ETHUSDT')
        base_keys = {(s['timestamp'], s['side']) for s in base_signals}
        tt_keys = {(s['timestamp'], s['side']) for s in tt_signals}
        self.assertTrue(tt_keys.issubset(base_keys))

    def test_no_conflicting_directions_at_same_timestamp(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=2)
        metrics = _synthetic_metrics(minutes, seed=2)
        config = OrderBlockOIConfig('base', 'oi')
        bars = oi_features(minutes, metrics, config)
        signals = generate_order_block_oi_signals(bars, config, 'ETHUSDT')
        timestamps = [s['timestamp'] for s in signals]
        self.assertEqual(len(timestamps), len(set(timestamps)))

    def test_signals_require_positive_risk_and_finite_atr(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=3)
        metrics = _synthetic_metrics(minutes, seed=3)
        config = OrderBlockOIConfig('base', 'oi')
        bars = oi_features(minutes, metrics, config)
        signals = generate_order_block_oi_signals(bars, config, 'ETHUSDT')
        for signal in signals:
            risk = signal['side'] * (signal['reference'] - signal['stop'])
            self.assertGreater(risk, 0)
            self.assertTrue(np.isfinite(signal['atr']))

    def test_fewer_or_equal_signals_than_s17_same_bars(self):
        # Adding a required OI-confirmation family can only be more selective
        # than S17's plain regime+structure+OBV trigger on identical bars.
        from l1_filter.order_block_continuation_scalp import generate_order_block_signals
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=4)
        metrics = _synthetic_metrics(minutes, seed=4)
        s17_config = OrderBlockContinuationConfig('s17', 'base')
        s18_config = OrderBlockOIConfig('s18', 'oi')
        bars = oi_features(minutes, metrics, s18_config)
        s17_signals = generate_order_block_signals(bars, s17_config, 'ETHUSDT')
        s18_signals = generate_order_block_oi_signals(bars, s18_config, 'ETHUSDT')
        self.assertLessEqual(len(s18_signals), len(s17_signals))

    def test_route_validation_rejects_unknown_route(self):
        with self.assertRaises(ValueError):
            OrderBlockOIConfig('bad', 'reversal')

    def test_oi_confirmation_blocks_a_short_squeeze_long_setup(self):
        # Falling OI while price rallies into the OB retest (a short squeeze,
        # not new long positioning) must not fire, even with a valid OB/OBV.
        index = pd.date_range('2026-01-01', periods=2, freq='15min', tz='UTC')
        bars = pd.DataFrame({
            # Bar 0 forms the OB but does not itself dip back into the zone
            # (stays above top=100) — the retest only happens on bar 1.
            'open': [101.2, 98.6], 'high': [102.0, 100.0], 'low': [101.0, 98.5],
            'close': [101.5, 99.8], 'atr': [1.0, 1.0],
            'htf_trend_up': [True, True], 'htf_trend_down': [False, False],
            'htf_adx': [25.0, 25.0], 'obv': [10.0, 11.0], 'obv_ema': [5.0, 5.0],
            'ob_bull_confirmed': [True, False], 'ob_bull_top': [100.0, np.nan],
            'ob_bull_bottom': [98.0, np.nan], 'ob_bear_confirmed': [False, False],
            'ob_bear_top': [np.nan, np.nan], 'ob_bear_bottom': [np.nan, np.nan],
            'oi_change': [0.0, -5000.0], 'toptrader_zscore': [0.0, 0.0],
        }, index=index)
        config = OrderBlockOIConfig('test', 'oi')
        signals = generate_order_block_oi_signals(bars, config, 'ETHUSDT')
        self.assertEqual(signals, [])

    def test_partial_r_and_trail_atr_are_configurable_and_validated(self):
        config = OrderBlockOIConfig('test', 'oi', partial_r=0.5, trail_atr=1.0)
        execution = config.execution()
        self.assertEqual(execution.partial_r, 0.5)
        self.assertEqual(execution.trail_atr, 1.0)
        with self.assertRaises(ValueError):
            OrderBlockOIConfig('bad', 'oi', partial_r=0)
        with self.assertRaises(ValueError):
            OrderBlockOIConfig('bad', 'oi', partial_r=10, target_r=5)

    def test_position_sizing_is_configurable_and_validated(self):
        config = OrderBlockOIConfig('test', 'oi', fixed_risk_usd=2.0, fixed_margin_usd=100.0,
                                    max_notional_equity=1.0, max_margin_fraction=0.4, leverage=5.0)
        execution = config.execution()
        self.assertEqual(execution.fixed_risk_usd, 2.0)
        self.assertEqual(execution.fixed_margin_usd, 100.0)
        self.assertEqual(execution.max_margin_fraction, 0.4)
        with self.assertRaises(ValueError):
            OrderBlockOIConfig('bad', 'oi', fixed_risk_usd=0)
        with self.assertRaises(ValueError):
            OrderBlockOIConfig('bad', 'oi', leverage=0.5)

    def test_trailing_and_hold_time_are_configurable_for_a_flat_target(self):
        # A flat 1:1 R:R, no-trailing exit (target_r=1.0) must be constructible.
        config = OrderBlockOIConfig('test', 'oi', target_r=1.0, partial_r=0.5,
                                    trailing=False, max_hold_minutes=90)
        execution = config.execution()
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.target_r, 1.0)
        self.assertEqual(execution.max_hold_minutes, 90)
        with self.assertRaises(ValueError):
            OrderBlockOIConfig('bad', 'oi', max_hold_minutes=0)
