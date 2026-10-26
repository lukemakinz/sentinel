import unittest

import numpy as np
import pandas as pd

from l1_filter.oi_state_transition_scalp import _confirmed_structure
from l1_filter.regime_playbook_scalp import (
    RegimePlaybookConfig,
    generate_regime_playbook_signals,
    regime_playbook_features,
)


def _minutes(close, start='2025-01-01', freq='15min'):
    index = pd.date_range(start, periods=len(close), freq=freq, tz='UTC')
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({
        'open': close,
        'high': close + 0.4,
        'low': close - 0.4,
        'close': close,
        'volume': 100.0,
        'taker_buy_volume': 55.0,
        'atr15': 1.0,
        'ema20': close,
        'regime': 0,
        'range_high': close + 1.0,
        'range_low': close - 1.0,
    }, index=index)


class RegimeLabelTests(unittest.TestCase):
    def test_four_hour_structure_maps_to_up_down_or_sideline(self):
        index = pd.date_range('2025-01-01', periods=8, freq='4h', tz='UTC')
        up = pd.DataFrame({
            'high': [2, 4, 3, 6, 5, 8, 7, 10],
            'low': [1, 2, 1.5, 3, 2.5, 5, 4, 7],
        }, index=index)
        down = pd.DataFrame({
            'high': [10, 8, 9, 6, 7, 4, 5, 2],
            'low': [8, 6, 7, 4, 5, 2, 3, 0.5],
        }, index=index)

        self.assertEqual(int(_confirmed_structure(up, width=1).iloc[-1]), 1)
        self.assertEqual(int(_confirmed_structure(down, width=1).iloc[-1]), -1)

    def test_mixed_swings_are_sideline_not_a_forced_trend(self):
        index = pd.date_range('2025-01-01', periods=8, freq='4h', tz='UTC')
        mixed = pd.DataFrame({
            'high': [3, 6, 4, 8, 5, 9, 6, 10],
            'low': [2, 4, 1, 3, 0, 2, -1, 1],
        }, index=index)
        self.assertEqual(int(_confirmed_structure(mixed, width=1).iloc[-1]), 0)


class PlaybookSignalTests(unittest.TestCase):
    def test_trend_only_emits_long_pullback_in_uptrend_and_ignores_sideline(self):
        bars = _minutes([100, 101, 100.2, 101.4, 101.1, 102.0, 101.2, 102.5])
        bars['regime'] = 1
        bars.loc[bars.index[0], 'regime'] = 0
        bars['ema20'] = 101.0
        bars.loc[bars.index[4], ['open', 'high', 'low', 'close']] = [
            101.2, 101.3, 100.7, 101.25]
        bars.loc[bars.index[6], ['open', 'high', 'low', 'close']] = [
            101.0, 101.1, 99.0, 99.2]
        bars.loc[bars.index[6], 'regime'] = 0
        bars.loc[bars.index[6], 'range_high'] = 101.0

        trend = generate_regime_playbook_signals(
            bars, RegimePlaybookConfig(route='trend_only'), 'SOLUSDT')
        switch = generate_regime_playbook_signals(
            bars, RegimePlaybookConfig(route='regime_switch'), 'SOLUSDT')

        self.assertEqual([s['side'] for s in trend], [1])
        self.assertTrue(any(s['setup'].startswith('sideline_fade') for s in switch))
        self.assertFalse(any(s['setup'].startswith('sideline_fade') for s in trend))

    def test_downtrend_only_allows_short_continuation(self):
        bars = _minutes([102, 101, 101.8, 100.6, 100.9, 99.8])
        bars['regime'] = -1
        bars['ema20'] = 101.0
        bars.loc[bars.index[4], ['open', 'high', 'low', 'close']] = [
            100.8, 101.3, 100.7, 100.75]

        signals = generate_regime_playbook_signals(
            bars, RegimePlaybookConfig(route='trend_only'), 'XRPUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], -1)

    def test_early_profit_execution_does_not_trail(self):
        execution = RegimePlaybookConfig().execution()
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.target_r, 1.0)
        self.assertEqual(execution.max_hold_minutes, 60)
