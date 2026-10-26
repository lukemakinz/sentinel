import unittest

import pandas as pd

from l1_filter.ny_orb_daytrade import (
    NyOrbConfig,
    generate_ny_orb_signals,
)


class NyOrbDaytradeTests(unittest.TestCase):
    def _bars(self, start, periods=40):
        index = pd.date_range(start, periods=periods, freq='5min', tz='UTC')
        return pd.DataFrame({
            'open': 100.0, 'high': 100.2, 'low': 99.8, 'close': 100.0,
            'volume': 20.0, 'taker_buy_volume': 12.0, 'atr': 1.0,
            'sma20': 99.0, 'daily_close': 100.5, 'or_high': 100.3, 'or_low': 99.7,
            'or_ready': True, 'or_width_ok': True, 'in_entry_window': True,
            'session_day': index.normalize(),
        }, index=index)

    def test_break_of_ny_range_with_daily_uptrend_is_long(self):
        bars = self._bars('2025-06-02 14:05')
        bars.loc[bars.index[2], ['high', 'close']] = [100.8, 100.7]
        signals = generate_ny_orb_signals(bars, NyOrbConfig(), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)

    def test_downtrend_does_not_take_the_long_break(self):
        bars = self._bars('2025-06-03 14:05')
        bars['sma20'] = 101.0
        bars['daily_close'] = 100.0
        bars.loc[bars.index[2], ['high', 'close']] = [100.8, 100.7]
        signals = generate_ny_orb_signals(bars, NyOrbConfig(), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_execution_is_dual_slot_hold_to_close_not_scalp(self):
        execution = NyOrbConfig().execution()
        self.assertEqual(execution.max_positions, 2)
        self.assertEqual(execution.fixed_risk_usd, 15.0)
        self.assertGreaterEqual(execution.target_r, 6.0)
        self.assertFalse(execution.trailing)
        self.assertGreaterEqual(execution.max_hold_minutes, 5 * 60)
