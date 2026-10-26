import unittest

import pandas as pd

from l1_filter.ny_asia_sweep_scalp import (
    NYAsiaSweepConfig,
    generate_ny_asia_sweep_signals,
)


class NYAsiaSweepTests(unittest.TestCase):
    def _bars(self, start, periods=24):
        index = pd.date_range(start, periods=periods, freq='5min', tz='UTC')
        return pd.DataFrame({
            'open': 100.0, 'high': 100.2, 'low': 99.8, 'close': 100.0,
            'volume': 20.0, 'taker_buy_volume': 12.0, 'atr1h': 1.0,
            'regime': 0, 'asia_high': 100.5, 'asia_low': 99.5,
            'asia_width_ok': True, 'sweep_ready': True,
            'in_sweep_window': True, 'session_day': index.normalize(),
        }, index=index)

    def test_us_open_sweep_of_asia_high_fades_short(self):
        bars = self._bars('2025-06-10 13:00')
        bars.loc[bars.index[1], ['high', 'close']] = [100.9, 100.8]
        bars.loc[bars.index[3], ['high', 'low', 'close']] = [100.6, 100.1, 100.2]
        signals = generate_ny_asia_sweep_signals(
            bars, NYAsiaSweepConfig(route='ny_sweep_fade'), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], -1)

    def test_held_sweep_is_not_faded(self):
        bars = self._bars('2025-06-11 13:00')
        bars.loc[bars.index[1:], ['high', 'close']] = [100.9, 100.8]
        signals = generate_ny_asia_sweep_signals(
            bars, NYAsiaSweepConfig(route='ny_sweep_fade'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_sideline_route_skips_downtrend(self):
        bars = self._bars('2025-06-12 13:00')
        bars['regime'] = -1
        bars.loc[bars.index[1], ['high', 'close']] = [100.9, 100.8]
        bars.loc[bars.index[3], ['high', 'low', 'close']] = [100.6, 100.1, 100.2]
        signals = generate_ny_asia_sweep_signals(
            bars, NYAsiaSweepConfig(route='ny_sweep_sideline'), 'SOLUSDT')
        self.assertEqual(signals, [])

    def test_early_profit_does_not_trail(self):
        execution = NYAsiaSweepConfig().execution()
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.target_r, 1.0)
        self.assertEqual(execution.max_hold_minutes, 90)
