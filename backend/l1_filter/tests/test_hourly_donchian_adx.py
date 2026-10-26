import unittest

import pandas as pd

from l1_filter.hourly_donchian_adx import (
    HourlyDonchianAdxConfig,
    generate_hourly_donchian_adx_signals,
)


class HourlyDonchianAdxTests(unittest.TestCase):
    def _bars(self, start, periods=24):
        index = pd.date_range(start, periods=periods, freq='h', tz='UTC')
        close = pd.Series(100.0, index=index)
        return pd.DataFrame({
            'open': close - 0.2, 'high': close + 0.3, 'low': close - 0.4,
            'close': close, 'volume': 80.0, 'taker_buy_volume': 40.0,
            'atr': 1.2, 'adx': 30.0, 'donchian_high': 101.0, 'donchian_low': 98.0,
            'session_day': index.normalize(),
        }, index=index)

    def test_close_through_hourly_channel_with_adx_is_long(self):
        bars = self._bars('2025-06-02')
        bars.loc[bars.index[10], ['high', 'close']] = [102.4, 102.1]
        bars.loc[bars.index[10], 'donchian_high'] = 101.5
        signals = generate_hourly_donchian_adx_signals(
            bars, HourlyDonchianAdxConfig(), 'SOLUSDT')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['side'], 1)

    def test_weak_adx_does_not_trade_the_break(self):
        bars = self._bars('2025-06-03')
        bars['adx'] = 12.0
        bars.loc[bars.index[10], ['high', 'close']] = [102.4, 102.1]
        bars.loc[bars.index[10], 'donchian_high'] = 101.5
        signals = generate_hourly_donchian_adx_signals(
            bars, HourlyDonchianAdxConfig(), 'XRPUSDT')
        self.assertEqual(signals, [])

    def test_execution_is_uncapped_dual_slot(self):
        execution = HourlyDonchianAdxConfig().execution()
        self.assertEqual(execution.max_positions, 2)
        self.assertEqual(execution.fixed_risk_usd, 15.0)
        self.assertGreaterEqual(execution.target_r, 8.0)
        self.assertFalse(execution.trailing)
        self.assertEqual(execution.max_hold_minutes, 1440)
