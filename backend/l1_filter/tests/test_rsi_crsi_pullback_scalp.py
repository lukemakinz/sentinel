import numpy as np
import pandas as pd
import unittest

from l1_filter.rsi_crsi_pullback_scalp import (
    RSICRSIPullbackConfig,
    _connors_rsi,
    generate_rsi_crsi_signals,
    rsi_crsi_features,
)


def _trending_minutes(periods=60 * 24 * 60, seed=0):
    """A noisy but persistently rising series with enough history for 4h
    EMA200 warmup, ADX, and CRSI's 100-bar rank window."""
    rng = np.random.default_rng(seed)
    index = pd.date_range('2025-01-01', periods=periods, freq='min', tz='UTC')
    drift = np.linspace(0, 40, periods)
    noise = np.cumsum(rng.normal(0, 0.05, periods))
    close = 100 + drift + noise
    high = close + np.abs(rng.normal(0.05, 0.02, periods))
    low = close - np.abs(rng.normal(0.05, 0.02, periods))
    open_ = close + rng.normal(0, 0.02, periods)
    volume = rng.uniform(5, 15, periods)
    taker = volume * rng.uniform(0.4, 0.6, periods)
    return pd.DataFrame({'open': open_, 'high': high, 'low': low, 'close': close,
                         'volume': volume, 'taker_buy_volume': taker}, index=index)


class ConnorsRSITests(unittest.TestCase):
    def test_bounded_between_0_and_100(self):
        minutes = _trending_minutes(periods=60 * 24 * 40)
        close = minutes.close.iloc[::15].reset_index(drop=True)
        crsi = _connors_rsi(close)
        valid = crsi.dropna()
        self.assertGreater(len(valid), 0)
        self.assertTrue((valid >= 0).all() and (valid <= 100).all())

    def test_is_prefix_invariant_no_lookahead(self):
        minutes = _trending_minutes(periods=60 * 24 * 40)
        close = minutes.close.iloc[::15].reset_index(drop=True)
        cutoff = len(close) - 50
        prefix = _connors_rsi(close.iloc[:cutoff])
        full = _connors_rsi(close).iloc[:cutoff]
        pd.testing.assert_series_equal(prefix, full)


class RSICRSIPullbackFeaturesTests(unittest.TestCase):
    def test_features_are_prefix_invariant(self):
        config = RSICRSIPullbackConfig('test', 'base')
        minutes = _trending_minutes(periods=60 * 24 * 60)
        cutoff = pd.Timestamp('2025-02-20', tz='UTC')
        prefix = rsi_crsi_features(minutes.loc[minutes.index < cutoff], config)
        full = rsi_crsi_features(minutes, config).loc[prefix.index]
        columns = ['atr', 'rsi2', 'crsi', 'htf_adx', 'htf_trend_up', 'htf_trend_down',
                   'sweep_level_long', 'sweep_level_short', 'stop_long', 'stop_short']
        pd.testing.assert_frame_equal(prefix[columns], full[columns])

    def test_htf_trend_never_uses_in_progress_4h_bar(self):
        # A step change at the very end of the series must not retroactively
        # flip htf_trend_up/down for bars inside the still-forming 4h window.
        config = RSICRSIPullbackConfig('test', 'base')
        minutes = _trending_minutes(periods=60 * 24 * 60)
        baseline = rsi_crsi_features(minutes, config)
        shocked = minutes.copy()
        last_4h_start = shocked.index[-1].floor('4h')
        mask = shocked.index >= last_4h_start
        shocked.loc[mask, ['open', 'high', 'low', 'close']] -= 10_000
        shocked_features = rsi_crsi_features(shocked, config)
        before_window = baseline.index[baseline.index < last_4h_start]
        pd.testing.assert_series_equal(
            baseline.loc[before_window, 'htf_trend_up'],
            shocked_features.loc[before_window, 'htf_trend_up'])


class RSICRSIPullbackSignalsTests(unittest.TestCase):
    def test_confluence_signals_are_a_subset_of_base_signals(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=1)
        base_config = RSICRSIPullbackConfig('base', 'base')
        confluence_config = RSICRSIPullbackConfig('confluence', 'confluence')
        bars = rsi_crsi_features(minutes, base_config)
        base_signals = generate_rsi_crsi_signals(bars, base_config, 'ETHUSDT')
        confluence_signals = generate_rsi_crsi_signals(bars, confluence_config, 'ETHUSDT')
        base_keys = {(s['timestamp'], s['side']) for s in base_signals}
        confluence_keys = {(s['timestamp'], s['side']) for s in confluence_signals}
        self.assertTrue(confluence_keys.issubset(base_keys))

    def test_no_conflicting_directions_at_same_timestamp(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=2)
        config = RSICRSIPullbackConfig('base', 'base')
        bars = rsi_crsi_features(minutes, config)
        signals = generate_rsi_crsi_signals(bars, config, 'ETHUSDT')
        timestamps = [s['timestamp'] for s in signals]
        self.assertEqual(len(timestamps), len(set(timestamps)))

    def test_long_signal_requires_positive_risk_and_known_atr(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=3)
        config = RSICRSIPullbackConfig('base', 'base')
        bars = rsi_crsi_features(minutes, config)
        signals = generate_rsi_crsi_signals(bars, config, 'ETHUSDT')
        for signal in signals:
            risk = signal['side'] * (signal['reference'] - signal['stop'])
            self.assertGreater(risk, 0)
            self.assertTrue(np.isfinite(signal['atr']))

    def test_route_validation_rejects_unknown_route(self):
        with self.assertRaises(ValueError):
            RSICRSIPullbackConfig('bad', 'reversal')
