import numpy as np
import pandas as pd
import unittest

from l1_filter.bollinger_event_scalp import (
    BollingerEventConfig,
    bollinger_event_features,
    liquidity_mss_signals,
)


def _minutes(periods=60 * 24 * 5):
    index = pd.date_range('2026-01-01', periods=periods, freq='min', tz='UTC')
    close = 100 + np.sin(np.arange(periods) / 300) + np.arange(periods) * 0.0001
    return pd.DataFrame({
        'open': close, 'high': close + .05, 'low': close - .05, 'close': close,
        'volume': np.full(periods, 10.0),
        'taker_buy_volume': np.full(periods, 5.0),
    }, index=index)


def _check_event_features_are_prefix_invariant():
    minutes = _minutes()
    cutoff = pd.Timestamp('2026-01-04', tz='UTC')
    prefix = bollinger_event_features(minutes.loc[minutes.index < cutoff])
    full = bollinger_event_features(minutes).loc[prefix.index]
    columns = [
        'bb_upper_prior', 'bandwidth_cutoff', 'pivot_high_prior',
        'prior_four_high', 'bandwidth_expansion_25', 'structure_bias_1h',
        'box_high', 'box_low',
    ]
    pd.testing.assert_frame_equal(prefix[columns], full[columns])


def _event_bars():
    index = pd.date_range('2026-01-05 08:15', periods=4, freq='15min', tz='UTC')
    return pd.DataFrame({
        'open': [99.3, 99.5, 100.3, 101.0],
        'high': [100.0, 100.1, 102.0, 101.5],
        'low': [98.9, 99.3, 100.2, 100.7],
        'close': [99.5, 99.8, 101.9, 101.2],
        'atr': [1.0] * 4,
        'bb_middle_prior': [102.0] * 4, 'bb_upper_prior': [104.0] * 4,
        'bb_lower_prior': [99.0] * 4, 'hourly_bandwidth': [.04] * 4,
        'hourly_bandwidth_extreme_cutoff': [.08] * 4,
        'hourly_bandwidth_extreme': [False] * 4,
        'bandwidth_expansion_25': [False, False, True, False],
        'structure_bias_1h': [0, 0, 1, 1],
        'pivot_high_prior': [101.0] * 4, 'pivot_low_prior': [98.0] * 4,
        'session': ['london'] * 4, 'session_date': ['2026-01-05'] * 4,
        'box_high': [104.0] * 4, 'box_low': [99.2] * 4,
    }, index=index)


def _check_liquidity_route_sequences_sweep_then_later_mss_and_serializes_evidence():
    bars = _event_bars()
    btc = bars.copy()
    btc[['open', 'high', 'low', 'close']] = [
        [100, 100.4, 99.2, 100.1],
        [100.1, 100.5, 99.2, 100.2],
        [100.2, 100.5, 99.3, 100.3],
        [100.3, 100.5, 99.3, 100.4],
    ]
    btc['box_low'] = 99.0
    config = BollingerEventConfig('test', 'liquidity_mss', 3)
    signals = liquidity_mss_signals(bars, btc, config, 'ETHUSDT')
    assert len(signals) == 1
    signal = signals[0]
    assert signal['timestamp'] == bars.index[2]
    assert signal['evidence']['passed_confirmations'] >= 3
    assert signal['evidence']['hard_conditions']['later_preknown_pivot_mss']
    assert signal['shadow_only'] is True


def _check_liquidity_route_rejects_btc_confirmation_before_alt_sweep():
    bars = _event_bars()
    btc = bars.copy()
    btc[['open', 'high', 'low', 'close']] = [
        [100, 100.2, 98.8, 99.8],
        [99.8, 100.2, 99.2, 100.0],
        [100.0, 100.2, 99.2, 100.0],
        [100.0, 100.2, 99.2, 100.0],
    ]
    btc['box_low'] = 99.0
    config = BollingerEventConfig('test', 'liquidity_mss', 3)
    assert liquidity_mss_signals(bars, btc, config, 'ETHUSDT') == []


class BollingerEventTests(unittest.TestCase):
    def test_event_features_are_prefix_invariant(self):
        _check_event_features_are_prefix_invariant()

    def test_liquidity_route_sequences_sweep_then_later_mss_and_serializes_evidence(self):
        _check_liquidity_route_sequences_sweep_then_later_mss_and_serializes_evidence()

    def test_liquidity_route_rejects_btc_confirmation_before_alt_sweep(self):
        _check_liquidity_route_rejects_btc_confirmation_before_alt_sweep()
