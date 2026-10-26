import importlib.util
import unittest

import numpy as np
import pandas as pd

from l1_filter.oi_state_transition_scalp import (
    OIStateTransitionConfig,
    _confirmed_pivots,
    _confirmed_structure,
    build_oi_state_transition_features,
    generate_oi_state_transition_signals,
)


class OIStateTransitionModuleTests(unittest.TestCase):
    def test_strategy_module_exists(self):
        self.assertIsNotNone(
            importlib.util.find_spec('l1_filter.oi_state_transition_scalp'))

    def test_confirmed_pivot_is_published_only_after_right_hand_bars_close(self):
        index = pd.date_range('2025-01-01', periods=5, freq='4h', tz='UTC')
        bars = pd.DataFrame({
            'high': [1.0, 2.0, 5.0, 2.0, 1.0],
            'low': [5.0, 4.0, 3.0, 4.0, 5.0],
        }, index=index)

        pivots = _confirmed_pivots(bars, width=2)

        self.assertTrue(pivots.latest_high.iloc[:4].isna().all())
        self.assertTrue(pivots.latest_low.iloc[:4].isna().all())
        self.assertEqual(pivots.latest_high.iloc[4], 5.0)
        self.assertEqual(pivots.latest_low.iloc[4], 3.0)
        self.assertEqual(pivots.latest_high_time.iloc[4], index[2])
        self.assertEqual(pivots.latest_low_time.iloc[4], index[2])

    def test_structure_requires_two_confirmed_higher_highs_and_lows(self):
        index = pd.date_range('2025-01-01', periods=6, freq='4h', tz='UTC')
        bars = pd.DataFrame({
            'high': [2.0, 4.0, 3.0, 5.0, 4.0, 6.0],
            'low': [1.0, 2.0, 1.0, 3.0, 2.0, 4.0],
        }, index=index)

        regime = _confirmed_structure(bars, width=1)

        self.assertTrue((regime.iloc[:5] == 0).all())
        self.assertEqual(regime.iloc[5], 1)

    def test_feature_builder_aligns_oi_at_bar_open_and_close(self):
        start = pd.Timestamp('2025-01-01', tz='UTC')
        end = start + pd.Timedelta(days=3)
        minute_index = pd.date_range(
            start, end - pd.Timedelta(minutes=1), freq='1min')
        base = 100 + np.arange(len(minute_index)) * 0.001
        minutes = pd.DataFrame({
            'open': base,
            'high': base + 0.2,
            'low': base - 0.2,
            'close': base + 0.05,
            'volume': 100.0,
            'taker_buy_volume': 55.0,
        }, index=minute_index)
        metric_index = pd.date_range(start, end, freq='5min')
        metrics = pd.DataFrame({
            'open_interest': 1000.0 + np.arange(len(metric_index)),
            'metrics_age_minutes': 5.0,
            'metrics_observed': True,
        }, index=metric_index)
        config = OIStateTransitionConfig(
            pivot_width=1, oi_reset_lookback_bars=2)

        bars = build_oi_state_transition_features(minutes, metrics, config)

        first = bars.iloc[0]
        self.assertEqual(first.oi_open, metrics.open_interest.iloc[0])
        self.assertEqual(first.oi_close, metrics.loc[bars.index[0], 'open_interest'])
        self.assertEqual(first.metrics_open_age_minutes, 5.0)
        self.assertEqual(first.metrics_age_minutes, 5.0)
        self.assertIn('htf_regime', bars)
        self.assertIn('oi_reset_threshold', bars)
        self.assertTrue(np.isfinite(bars.oi_reset_threshold.iloc[2]))

    def test_config_rejects_nonpositive_minimum_target(self):
        with self.assertRaises(ValueError):
            OIStateTransitionConfig(minimum_target_r=0)


class GenerateSignalsTests(unittest.TestCase):
    def _bars(self, side=1, confirm_offset=1, rebuild=True, fresh=True,
              repeat_level=False):
        index = pd.date_range('2025-05-01', periods=7, freq='15min', tz='UTC')
        bars = pd.DataFrame(index=index)
        bars['open'] = 100.0
        bars['high'] = 100.2
        bars['low'] = 99.8
        bars['close'] = 100.0
        bars['atr15'] = 1.0
        bars['atr1h'] = 2.0
        bars['htf_regime'] = side
        bars['liquidity_low'] = 99.0
        bars['liquidity_high'] = 101.0
        bars['liquidity_low_time'] = index[0] - pd.Timedelta(hours=1)
        bars['liquidity_high_time'] = index[0] - pd.Timedelta(hours=1)
        bars['mss_high'] = 101.0
        bars['mss_low'] = 99.0
        bars['opposing_1h_high'] = 110.0
        bars['opposing_1h_low'] = 90.0
        bars['oi_open'] = 1000.0
        bars['oi_close'] = 995.0
        bars['oi_reset_threshold'] = 2.0
        bars['metrics_age_minutes'] = 0.0
        bars['volume'] = 100.0
        bars['taker_buy_volume'] = 50.0

        if side == 1:
            bars.loc[index[0], ['open', 'high', 'low', 'close']] = [
                99.2, 100.0, 98.5, 99.5]
            bars.loc[index[confirm_offset], ['open', 'high', 'low', 'close']] = [
                100.8, 102.2, 100.7, 102.0]
            bars.loc[index[confirm_offset], 'taker_buy_volume'] = 60.0
        else:
            bars.loc[index[0], ['open', 'high', 'low', 'close']] = [
                100.8, 101.5, 100.0, 100.5]
            bars.loc[index[confirm_offset], ['open', 'high', 'low', 'close']] = [
                99.2, 99.3, 97.8, 98.0]
            bars.loc[index[confirm_offset], 'taker_buy_volume'] = 40.0

        bars.loc[index[confirm_offset], 'oi_close'] = 998.0 if rebuild else 996.0
        if not fresh:
            bars.loc[index[confirm_offset], 'metrics_age_minutes'] = 15.0

        if repeat_level:
            second_sweep = index[3]
            second_confirmation = index[4]
            if side == 1:
                bars.loc[second_sweep, ['open', 'high', 'low', 'close']] = [
                    99.2, 100.0, 98.4, 99.5]
                bars.loc[second_confirmation, ['open', 'high', 'low', 'close']] = [
                    100.8, 102.2, 100.7, 102.0]
                bars.loc[second_confirmation, 'taker_buy_volume'] = 60.0
            bars.loc[second_confirmation, 'oi_close'] = 998.0
        return bars

    def test_long_requires_reset_then_mss_flow_and_rebuild(self):
        bars = self._bars(side=1)

        signals = generate_oi_state_transition_signals(
            bars, OIStateTransitionConfig(), 'SOLUSDT')

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['timestamp'], bars.index[1])
        self.assertEqual(signals[0]['side'], 1)
        self.assertAlmostEqual(signals[0]['stop'], 98.2)
        self.assertAlmostEqual(signals[0]['target_price'], 110.0)
        self.assertEqual(signals[0]['evidence']['oi_reset'], 5.0)
        self.assertEqual(signals[0]['evidence']['oi_rebuild'], 3.0)

    def test_short_is_symmetric(self):
        bars = self._bars(side=-1)

        signals = generate_oi_state_transition_signals(
            bars, OIStateTransitionConfig(), 'XRPUSDT')

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], -1)
        self.assertAlmostEqual(signals[0]['stop'], 101.8)
        self.assertAlmostEqual(signals[0]['target_price'], 90.0)

    def test_missing_rebuild_rejects_setup(self):
        signals = generate_oi_state_transition_signals(
            self._bars(rebuild=False), OIStateTransitionConfig(), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_stale_oi_rejects_confirmation(self):
        signals = generate_oi_state_transition_signals(
            self._bars(fresh=False), OIStateTransitionConfig(), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_confirmation_after_four_subsequent_bars_is_too_late(self):
        signals = generate_oi_state_transition_signals(
            self._bars(confirm_offset=5), OIStateTransitionConfig(), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_consumed_liquidity_level_cannot_generate_second_entry(self):
        signals = generate_oi_state_transition_signals(
            self._bars(repeat_level=True), OIStateTransitionConfig(), 'SOLUSDT')
        self.assertEqual(len(signals), 1)

    def test_execution_is_market_only_without_trailing_or_partials(self):
        execution = OIStateTransitionConfig().execution()
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.partial_fraction, 0.0)
        self.assertEqual(execution.leverage, 5.0)
        self.assertEqual(execution.risk_fraction, 0.002)
        self.assertEqual(execution.max_hold_minutes, 240)
