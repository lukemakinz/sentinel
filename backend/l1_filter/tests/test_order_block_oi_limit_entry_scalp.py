import numpy as np
import pandas as pd
import unittest

from l1_filter.order_block_oi_limit_entry_scalp import (
    OrderBlockLimitEntryConfig,
    generate_limit_entry_signals,
    limit_entry_features,
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
        'open_interest': oi, 'open_interest_value': oi * 2000,
        'toptrader_account_ratio': toptrader, 'toptrader_position_ratio': toptrader,
        'retail_account_ratio': toptrader,
        'taker_buy_sell_vol_ratio': np.abs(rng.normal(1.0, 0.3, len(index))),
    }, index=index)


class OrderBlockLimitEntrySignalsTests(unittest.TestCase):
    def test_signals_carry_a_resting_limit_at_the_ote_level(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=1)
        metrics = _synthetic_metrics(minutes, seed=1)
        config = OrderBlockLimitEntryConfig('test', 'limit_entry')
        bars = limit_entry_features(minutes, metrics, config)
        signals = generate_limit_entry_signals(bars, config, 'ETHUSDT')
        self.assertGreater(len(signals), 0)
        for signal in signals:
            self.assertIn('limit_price', signal)
            self.assertEqual(signal['limit_ttl_minutes'], config.limit_ttl_minutes)
            risk = signal['side'] * (signal['limit_price'] - signal['stop'])
            self.assertGreater(risk, 0)

    def test_ote_price_is_the_exact_configured_fraction_of_a_hand_built_zone(self):
        index = pd.date_range('2026-01-01', periods=1, freq='15min', tz='UTC')
        bars = pd.DataFrame({
            'atr': [1.0], 'low': [98.5], 'high': [100.5], 'close': [99.8], 'open': [99.0],
            'htf_trend_up': [True], 'htf_trend_down': [False], 'htf_adx': [25.0],
            'obv': [10.0], 'obv_ema': [5.0],
            'ob_bull_confirmed': [True], 'ob_bull_top': [100.0], 'ob_bull_bottom': [98.0],
            'ob_bear_confirmed': [False], 'ob_bear_top': [np.nan], 'ob_bear_bottom': [np.nan],
            'oi_change': [0.0],
        }, index=index)
        config = OrderBlockLimitEntryConfig('test', 'limit_entry', ote_ratio=0.25)
        signals = generate_limit_entry_signals(bars, config, 'ETHUSDT')
        # Zone confirms and the same bar's own low (98.5) already touches it
        # (top=100, low<=top) with close(99.8)>=bottom(98): fires immediately.
        self.assertEqual(len(signals), 1)
        # bottom(98.0) + 0.25 * (top(100.0) - bottom(98.0)) = 98.5
        self.assertAlmostEqual(signals[0]['limit_price'], 98.5)

    def test_killzone_route_only_fires_inside_the_trading_window(self):
        from l1_filter.bollinger_regime_scalp import _in_trading_window
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=3)
        metrics = _synthetic_metrics(minutes, seed=3)
        config = OrderBlockLimitEntryConfig('test', 'limit_entry_killzone')
        bars = limit_entry_features(minutes, metrics, config)
        signals = generate_limit_entry_signals(bars, config, 'ETHUSDT')
        self.assertGreater(len(signals), 0)
        self.assertTrue(all(_in_trading_window(s['timestamp']) for s in signals))

    def test_killzone_route_yields_fewer_or_equal_candidates(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=4)
        metrics = _synthetic_metrics(minutes, seed=4)
        all_day = OrderBlockLimitEntryConfig('all_day', 'limit_entry')
        killzone = OrderBlockLimitEntryConfig('killzone', 'limit_entry_killzone')
        bars = limit_entry_features(minutes, metrics, all_day)
        all_day_signals = generate_limit_entry_signals(bars, all_day, 'ETHUSDT')
        killzone_signals = generate_limit_entry_signals(bars, killzone, 'ETHUSDT')
        self.assertLessEqual(len(killzone_signals), len(all_day_signals))

    def test_no_conflicting_directions_at_same_timestamp(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=5)
        metrics = _synthetic_metrics(minutes, seed=5)
        config = OrderBlockLimitEntryConfig('test', 'limit_entry')
        bars = limit_entry_features(minutes, metrics, config)
        signals = generate_limit_entry_signals(bars, config, 'ETHUSDT')
        timestamps = [s['timestamp'] for s in signals]
        self.assertEqual(len(timestamps), len(set(timestamps)))

    def test_route_validation_rejects_unknown_route(self):
        with self.assertRaises(ValueError):
            OrderBlockLimitEntryConfig('bad', 'market')

    def test_ote_ratio_and_target_r_are_validated(self):
        with self.assertRaises(ValueError):
            OrderBlockLimitEntryConfig('bad', 'limit_entry', ote_ratio=1.5)
        with self.assertRaises(ValueError):
            OrderBlockLimitEntryConfig('bad', 'limit_entry', partial_r=5, target_r=5)


class OrderBlockLimitConcessionSignalsTests(unittest.TestCase):
    def test_concession_price_is_close_minus_atr_fraction_for_a_long(self):
        index = pd.date_range('2026-01-01', periods=1, freq='15min', tz='UTC')
        bars = pd.DataFrame({
            'atr': [1.0], 'low': [98.5], 'high': [100.5], 'close': [99.8], 'open': [99.0],
            'htf_trend_up': [True], 'htf_trend_down': [False], 'htf_adx': [25.0],
            'obv': [10.0], 'obv_ema': [5.0],
            'ob_bull_confirmed': [True], 'ob_bull_top': [100.0], 'ob_bull_bottom': [98.0],
            'ob_bear_confirmed': [False], 'ob_bear_top': [np.nan], 'ob_bear_bottom': [np.nan],
            'oi_change': [0.0],
        }, index=index)
        config = OrderBlockLimitEntryConfig('test', 'limit_entry_concession',
                                            limit_concession_atr=0.25)
        signals = generate_limit_entry_signals(bars, config, 'ETHUSDT')
        self.assertEqual(len(signals), 1)
        # close(99.8) - 0.25*atr(1.0) = 99.55, still inside the zone [98, 100].
        self.assertAlmostEqual(signals[0]['limit_price'], 99.55)

    def test_concession_price_never_asks_outside_the_zone(self):
        index = pd.date_range('2026-01-01', periods=1, freq='15min', tz='UTC')
        bars = pd.DataFrame({
            # A large concession (2.0x ATR) would fall below the zone bottom
            # (98.0) — must be clamped to the zone, not asked for outside it.
            'atr': [1.0], 'low': [98.1], 'high': [100.5], 'close': [98.3], 'open': [98.0],
            'htf_trend_up': [True], 'htf_trend_down': [False], 'htf_adx': [25.0],
            'obv': [10.0], 'obv_ema': [5.0],
            'ob_bull_confirmed': [True], 'ob_bull_top': [100.0], 'ob_bull_bottom': [98.0],
            'ob_bear_confirmed': [False], 'ob_bear_top': [np.nan], 'ob_bear_bottom': [np.nan],
            'oi_change': [0.0],
        }, index=index)
        config = OrderBlockLimitEntryConfig('test', 'limit_entry_concession',
                                            limit_concession_atr=2.0)
        signals = generate_limit_entry_signals(bars, config, 'ETHUSDT')
        self.assertEqual(len(signals), 1)
        self.assertAlmostEqual(signals[0]['limit_price'], 98.0)

    def test_concession_route_yields_more_or_equal_candidates_than_ote_route(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=6)
        metrics = _synthetic_metrics(minutes, seed=6)
        ote_config = OrderBlockLimitEntryConfig('ote', 'limit_entry')
        concession_config = OrderBlockLimitEntryConfig('concession', 'limit_entry_concession')
        bars = limit_entry_features(minutes, metrics, ote_config)
        ote_signals = generate_limit_entry_signals(bars, ote_config, 'ETHUSDT')
        concession_signals = generate_limit_entry_signals(bars, concession_config, 'ETHUSDT')
        self.assertGreaterEqual(len(concession_signals), len(ote_signals))

    def test_concession_killzone_route_only_fires_inside_the_trading_window(self):
        from l1_filter.bollinger_regime_scalp import _in_trading_window
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=3)
        metrics = _synthetic_metrics(minutes, seed=3)
        config = OrderBlockLimitEntryConfig('test', 'limit_entry_concession_killzone')
        bars = limit_entry_features(minutes, metrics, config)
        signals = generate_limit_entry_signals(bars, config, 'ETHUSDT')
        self.assertGreater(len(signals), 0)
        self.assertTrue(all(_in_trading_window(s['timestamp']) for s in signals))

    def test_limit_concession_atr_is_validated(self):
        with self.assertRaises(ValueError):
            OrderBlockLimitEntryConfig('bad', 'limit_entry_concession', limit_concession_atr=0)
