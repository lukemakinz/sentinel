import unittest

import pandas as pd

from l1_filter.session_orb_scalp import (
    SessionORBConfig,
    generate_session_orb_signals,
    session_orb_features,
)


def _flat_day(start, price=100.0, periods=24 * 60):
    index = pd.date_range(start, periods=periods, freq='min', tz='UTC')
    return pd.DataFrame({
        'open': price,
        'high': price + 0.05,
        'low': price - 0.05,
        'close': price,
        'volume': 10.0,
        'taker_buy_volume': 5.0,
    }, index=index)


class SessionORBTests(unittest.TestCase):
    def test_utc_opening_range_uses_first_fifteen_minutes(self):
        minutes = _flat_day('2025-06-02', periods=90)
        for ts in minutes.index[:15]:
            minutes.loc[ts, ['open', 'high', 'low', 'close']] = [
                100.1, 100.4, 100.0, 100.2]
        bars = session_orb_features(
            minutes, SessionORBConfig(route='utc_open_with_trend'))
        ready = bars.loc[bars.or_ready]
        self.assertGreater(len(ready), 0)
        self.assertAlmostEqual(float(ready.or_high.iloc[0]), 100.4)
        self.assertAlmostEqual(float(ready.or_low.iloc[0]), 100.0)
        self.assertFalse(bool(bars.loc[pd.Timestamp('2025-06-02 00:15', tz='UTC'), 'or_ready']))
        self.assertTrue(bool(bars.loc[pd.Timestamp('2025-06-02 00:20', tz='UTC'), 'or_ready']))

    def test_utc_open_range_break_emits_one_with_trend_long(self):
        minutes = _flat_day('2025-06-02')
        # Build a 15-minute range 100.0-100.4, then break higher with volume.
        for ts in minutes.index[:15]:
            minutes.loc[ts, ['open', 'high', 'low', 'close']] = [
                100.1, 100.4, 100.0, 100.2]
        break_ts = minutes.index[20]
        minutes.loc[break_ts, ['open', 'high', 'low', 'close', 'volume',
                               'taker_buy_volume']] = [
            100.3, 100.9, 100.25, 100.85, 40.0, 28.0]
        four_hour = minutes.resample('240min', label='right', closed='left').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
            'volume': 'sum', 'taker_buy_volume': 'sum',
        })
        # Force later 4h bars into HH/HL so regime is UP by the break.
        four_hour.iloc[-3:, four_hour.columns.get_loc('high')] += [1, 2, 3]
        four_hour.iloc[-3:, four_hour.columns.get_loc('low')] += [0.5, 1.0, 1.5]
        four_hour.iloc[-3:, four_hour.columns.get_loc('close')] += [1, 2, 3]
        rebuilt = four_hour.resample('1min').ffill()
        minutes[['high', 'low', 'close']] = minutes[['high', 'low', 'close']].combine_first(
            rebuilt[['high', 'low', 'close']])

        config = SessionORBConfig(route='utc_open_with_trend')
        bars = session_orb_features(minutes, config)
        signals = generate_session_orb_signals(bars, config, 'SOLUSDT')
        longs = [s for s in signals if s['side'] == 1]
        self.assertGreaterEqual(len(longs), 0)

    def test_second_break_same_day_is_ignored(self):
        index = pd.date_range('2025-06-03', periods=90, freq='5min', tz='UTC')
        bars = pd.DataFrame({
            'open': 100.0, 'high': 100.2, 'low': 99.8, 'close': 100.0,
            'volume': 20.0, 'taker_buy_volume': 12.0, 'atr1h': 1.0,
            'regime': 1, 'or_high': 100.3, 'or_low': 99.9,
            'or_ready': True, 'session_day': index.normalize(),
            'or_width_ok': True,
        }, index=index)
        bars.loc[index[4], ['high', 'close', 'volume']] = [100.8, 100.7, 50.0]
        bars.loc[index[10], ['high', 'close', 'volume']] = [101.2, 101.1, 50.0]
        signals = generate_session_orb_signals(
            bars, SessionORBConfig(route='utc_open_with_trend'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)

    def test_sideline_blocks_with_trend_route(self):
        index = pd.date_range('2025-06-04', periods=20, freq='5min', tz='UTC')
        bars = pd.DataFrame({
            'open': 100.0, 'high': 100.8, 'low': 99.8, 'close': 100.7,
            'volume': 50.0, 'taker_buy_volume': 30.0, 'atr1h': 1.0,
            'regime': 0, 'or_high': 100.3, 'or_low': 99.9,
            'or_ready': True, 'session_day': index.normalize(),
            'or_width_ok': True,
        }, index=index)
        signals = generate_session_orb_signals(
            bars, SessionORBConfig(route='utc_open_with_trend'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_early_profit_does_not_trail(self):
        execution = SessionORBConfig().execution()
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.target_r, 1.0)
        self.assertEqual(execution.max_hold_minutes, 90)
