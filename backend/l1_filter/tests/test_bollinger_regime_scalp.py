import numpy as np
import pandas as pd
import unittest

from l1_filter.bollinger_regime_scalp import (
    BollingerRouteConfig,
    _bands,
    bollinger_features,
    liquidity_failure_smt_signals,
)


def _minutes(periods=60 * 24 * 25):
    index = pd.date_range('2026-01-01', periods=periods, freq='min', tz='UTC')
    close = 100 + np.sin(np.arange(periods) / 500) + np.arange(periods) * 0.0001
    return pd.DataFrame({
        'open': close,
        'high': close + 0.05,
        'low': close - 0.05,
        'close': close,
        'volume': np.full(periods, 10.0),
        'taker_buy_volume': np.full(periods, 5.0),
    }, index=index)


class BollingerRegimeTests(unittest.TestCase):
    def test_bands_use_population_sigma_and_freeze_prior_reference(self):
        close = pd.Series(range(1, 22), dtype=float)
        bands = _bands(close, 20, 2.0)
        expected_sigma = np.std(np.arange(1, 21), ddof=0)
        self.assertEqual(bands.loc[19, 'bb_upper'], 10.5 + 2 * expected_sigma)
        self.assertTrue(np.isnan(bands.loc[18, 'bb_upper']))
        prior_upper = bands.bb_upper.shift(1)
        changed = close.copy()
        changed.iloc[20] = 10_000
        changed_bands = _bands(changed, 20, 2.0)
        self.assertEqual(prior_upper.iloc[20], changed_bands.bb_upper.shift(1).iloc[20])

    def test_features_are_prefix_invariant(self):
        config = BollingerRouteConfig(
            'test', 'squeeze_expansion', bandwidth_lookback=40,
            hourly_bandwidth_lookback=20,
        )
        minutes = _minutes(60 * 24 * 5)
        cutoff = pd.Timestamp('2026-01-04', tz='UTC')
        prefix = bollinger_features(minutes.loc[minutes.index < cutoff], config)
        full = bollinger_features(minutes, config).loc[prefix.index]
        columns = [
            'bb_middle_prior', 'bb_upper_prior', 'bb_lower_prior',
            'bandwidth_cutoff', 'prior_squeeze_count',
            'hourly_bandwidth_extreme_cutoff', 'box_high', 'box_low',
        ]
        pd.testing.assert_frame_equal(prefix[columns], full[columns])

    def test_liquidity_failure_requires_btc_nonconfirmation_and_deduplicates_session(self):
        config = BollingerRouteConfig(
            'test', 'liquidity_failure_smt', bandwidth_lookback=40,
            hourly_bandwidth_lookback=20,
        )
        index = pd.date_range('2026-01-05 08:15', periods=2, freq='15min', tz='UTC')
        base = pd.DataFrame({
            'open': [99.8, 99.8], 'high': [100.5, 100.5], 'low': [98.6, 98.6],
            'close': [100.2, 100.2], 'atr': [1.0, 1.0],
            'bb_middle_prior': [102.0, 102.0], 'bb_upper_prior': [104.0, 104.0],
            'bb_lower_prior': [99.0, 99.0], 'hourly_bandwidth': [0.04, 0.04],
            'hourly_bandwidth_extreme_cutoff': [0.08, 0.08],
            'hourly_bandwidth_extreme': [False, False],
            'session': ['london', 'london'], 'session_date': ['2026-01-05', '2026-01-05'],
            'box_high': [105.0, 105.0], 'box_low': [99.2, 99.2],
        }, index=index)
        btc = base.copy()
        btc[['open', 'high', 'low', 'close']] = [100.0, 100.5, 99.2, 100.1]
        btc['box_low'] = 99.0
        signals = liquidity_failure_smt_signals(base, btc, config, 'ETHUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['limit_price'], 100.0)
        self.assertEqual(signals[0]['target_price'], 102.0)
        btc['low'] = 98.0
        self.assertEqual(liquidity_failure_smt_signals(base, btc, config, 'ETHUSDT'), [])

    def test_liquidity_failure_vetoes_btc_sweep_earlier_in_same_session(self):
        config = BollingerRouteConfig(
            'test', 'liquidity_failure_smt', bandwidth_lookback=40,
            hourly_bandwidth_lookback=20,
        )
        index = pd.date_range('2026-01-05 08:15', periods=2, freq='15min', tz='UTC')
        alt = pd.DataFrame({
            'open': [100.0, 99.8], 'high': [100.3, 100.5], 'low': [99.4, 98.6],
            'close': [100.0, 100.2], 'atr': [1.0, 1.0],
            'bb_middle_prior': [102.0, 102.0], 'bb_upper_prior': [104.0, 104.0],
            'bb_lower_prior': [99.0, 99.0], 'hourly_bandwidth': [0.04, 0.04],
            'hourly_bandwidth_extreme_cutoff': [0.08, 0.08],
            'hourly_bandwidth_extreme': [False, False],
            'session': ['london', 'london'], 'session_date': ['2026-01-05', '2026-01-05'],
            'box_high': [105.0, 105.0], 'box_low': [99.2, 99.2],
        }, index=index)
        btc = alt.copy()
        btc[['open', 'high', 'low', 'close']] = [
            [100.0, 100.2, 98.8, 99.8],
            [99.8, 100.2, 99.2, 100.0],
        ]
        btc['box_low'] = 99.0
        self.assertEqual(liquidity_failure_smt_signals(alt, btc, config, 'ETHUSDT'), [])
