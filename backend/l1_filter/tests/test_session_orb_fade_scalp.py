import unittest

import pandas as pd

from l1_filter.session_orb_fade_scalp import (
    SessionORBFadeConfig,
    generate_session_orb_fade_signals,
)


class SessionORBFadeTests(unittest.TestCase):
    def _bars(self, start, periods=24):
        index = pd.date_range(start, periods=periods, freq='5min', tz='UTC')
        return pd.DataFrame({
            'open': 100.0, 'high': 100.2, 'low': 99.8, 'close': 100.0,
            'volume': 20.0, 'taker_buy_volume': 12.0, 'atr1h': 1.0,
            'regime': 0, 'or_high': 100.3, 'or_low': 99.9,
            'or_ready': True, 'session_day': index.normalize(),
            'or_width_ok': True, 'in_trade_window': True,
        }, index=index)

    def test_failed_upside_break_fades_short(self):
        bars = self._bars('2025-06-05')
        bars.loc[bars.index[2], ['high', 'close']] = [100.8, 100.7]
        bars.loc[bars.index[4], ['high', 'low', 'close']] = [100.4, 100.0, 100.15]
        signals = generate_session_orb_fade_signals(
            bars, SessionORBFadeConfig(route='utc_failed_fade'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], -1)
        self.assertGreater(signals[0]['stop'], signals[0]['reference'])

    def test_held_breakout_is_not_faded(self):
        bars = self._bars('2025-06-06')
        bars.loc[bars.index[2:], ['high', 'close']] = [100.9, 100.7]
        bars.loc[bars.index[4], ['high', 'close']] = [101.1, 101.0]
        signals = generate_session_orb_fade_signals(
            bars, SessionORBFadeConfig(route='utc_failed_fade'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_london_sideline_route_ignores_trend_days(self):
        bars = self._bars('2025-06-07')
        bars['regime'] = 1
        bars.loc[bars.index[2], ['high', 'close']] = [100.8, 100.7]
        bars.loc[bars.index[4], ['high', 'low', 'close']] = [100.4, 100.0, 100.15]
        signals = generate_session_orb_fade_signals(
            bars, SessionORBFadeConfig(route='london_sideline_fade'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_early_profit_does_not_trail(self):
        execution = SessionORBFadeConfig().execution()
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.target_r, 1.0)
        self.assertEqual(execution.max_hold_minutes, 90)
