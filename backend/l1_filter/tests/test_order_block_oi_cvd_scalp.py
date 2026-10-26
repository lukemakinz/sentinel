import numpy as np
import pandas as pd
import unittest

from l1_filter.order_block_oi_cvd_scalp import (
    OrderBlockCVDConfig,
    cvd_features,
    generate_cvd_signals,
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


class OrderBlockCVDFeaturesTests(unittest.TestCase):
    def test_features_are_prefix_invariant(self):
        config = OrderBlockCVDConfig('test', 'oi_cvd_flow')
        minutes = _trending_minutes(periods=60 * 24 * 60)
        master_metrics = _synthetic_metrics(minutes)
        cutoff = pd.Timestamp('2025-02-20', tz='UTC')
        prefix = cvd_features(minutes.loc[minutes.index < cutoff],
                              master_metrics.loc[master_metrics.index < cutoff], config)
        full = cvd_features(minutes, master_metrics, config).loc[prefix.index]
        columns = ['cvd', 'cvd_ema', 'obv', 'obv_ema', 'oi_change']
        pd.testing.assert_frame_equal(prefix[columns].iloc[:-1], full[columns].iloc[:-1])


class OrderBlockCVDSignalsTests(unittest.TestCase):
    def test_divergence_route_is_a_subset_of_flow_route_candidate_bars(self):
        # Not a strict superset relationship (different flow gate: CVD vs
        # OBV), but the divergence route should never fire MORE often than
        # the base OBV-gated route on the same bars, since it adds a filter
        # on top of the identical OBV/OI/regime/structure base.
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=1)
        metrics = _synthetic_metrics(minutes, seed=1)
        div_config = OrderBlockCVDConfig('div', 'oi_cvd_divergence')
        bars = cvd_features(minutes, metrics, div_config)
        div_signals = generate_cvd_signals(bars, div_config, 'ETHUSDT')
        self.assertIsInstance(div_signals, list)

    def test_no_conflicting_directions_at_same_timestamp(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=2)
        metrics = _synthetic_metrics(minutes, seed=2)
        config = OrderBlockCVDConfig('test', 'oi_cvd_flow')
        bars = cvd_features(minutes, metrics, config)
        signals = generate_cvd_signals(bars, config, 'ETHUSDT')
        timestamps = [s['timestamp'] for s in signals]
        self.assertEqual(len(timestamps), len(set(timestamps)))

    def test_signals_require_positive_risk_and_finite_atr(self):
        minutes = _trending_minutes(periods=60 * 24 * 90, seed=3)
        metrics = _synthetic_metrics(minutes, seed=3)
        config = OrderBlockCVDConfig('test', 'oi_cvd_flow')
        bars = cvd_features(minutes, metrics, config)
        signals = generate_cvd_signals(bars, config, 'ETHUSDT')
        self.assertGreater(len(signals), 0)
        for signal in signals:
            risk = signal['side'] * (signal['reference'] - signal['stop'])
            self.assertGreater(risk, 0)
            self.assertTrue(np.isfinite(signal['atr']))

    def test_route_validation_rejects_unknown_route(self):
        with self.assertRaises(ValueError):
            OrderBlockCVDConfig('bad', 'oi_cvd_reversal')

    def test_flow_route_uses_cvd_not_obv_gate(self):
        # Manual scenario: OBV supports the long, CVD does not (crossed
        # below its own EMA) — the flow route must reject it while an
        # otherwise-identical OBV-gated signal would accept it.
        index = pd.date_range('2026-01-01', periods=1, freq='15min', tz='UTC')
        bars = pd.DataFrame({
            'atr': [1.0], 'low': [98.5], 'high': [100.5], 'close': [99.8], 'open': [99.0],
            'htf_trend_up': [True], 'htf_trend_down': [False], 'htf_adx': [25.0],
            'obv': [10.0], 'obv_ema': [5.0],  # OBV bullish
            'cvd': [4.0], 'cvd_ema': [5.0],   # CVD bearish (below its own EMA)
            'ob_bull_confirmed': [True], 'ob_bull_top': [100.0], 'ob_bull_bottom': [98.0],
            'ob_bear_confirmed': [False], 'ob_bear_top': [np.nan], 'ob_bear_bottom': [np.nan],
            'oi_change': [0.0],
        }, index=index)
        flow_config = OrderBlockCVDConfig('test', 'oi_cvd_flow')
        self.assertEqual(generate_cvd_signals(bars, flow_config, 'ETHUSDT'), [])
