import unittest

import numpy as np
import pandas as pd

from l1_filter.global_direction_oi import (
    GlobalDirectionConfig,
    OIExecutionConfig,
    _asset_snapshot,
    global_direction_series,
    oi_oscillator,
)


def _daily(close):
    index = pd.date_range('2024-01-01', periods=len(close), freq='1D', tz='UTC')
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({
        'open': close * 0.999,
        'high': close * 1.01,
        'low': close * 0.99,
        'close': close,
        'volume': 1.0,
        'taker_buy_volume': 0.5,
        'close_time': index + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1),
    }, index=index)


class GlobalDirectionTests(unittest.TestCase):
    def test_labels_broad_uptrend_and_downtrend(self):
        up = np.linspace(100, 300, 280)
        down = np.linspace(300, 100, 280)
        config = GlobalDirectionConfig(confirmation_days=1)
        up_daily = {symbol: _daily(up * scale) for symbol, scale in (
            ('BTCUSDT', 1.0), ('ETHUSDT', 0.5), ('SOLUSDT', 0.1))}
        down_daily = {symbol: _daily(down * scale) for symbol, scale in (
            ('BTCUSDT', 1.0), ('ETHUSDT', 0.5), ('SOLUSDT', 0.1))}
        decision = '2024-10-06'
        up_result = global_direction_series(up_daily, decision, '2024-10-07', config)
        down_result = global_direction_series(down_daily, decision, '2024-10-07', config)
        self.assertEqual(up_result.regime.iloc[-1], 'UP')
        self.assertEqual(down_result.regime.iloc[-1], 'DOWN')

    def test_current_unclosed_bar_cannot_change_regime(self):
        close = np.linspace(100, 250, 280)
        daily = {symbol: _daily(close * scale) for symbol, scale in (
            ('BTCUSDT', 1.0), ('ETHUSDT', 0.5), ('SOLUSDT', 0.1))}
        decision = pd.Timestamp('2024-10-06', tz='UTC')
        baseline = global_direction_series(
            daily, decision, decision + pd.Timedelta(days=1),
            GlobalDirectionConfig(confirmation_days=1))
        for frame in daily.values():
            frame.loc[decision, ['open', 'high', 'low', 'close']] = [1, 1, 1, 1]
        changed = global_direction_series(
            daily, decision, decision + pd.Timedelta(days=1),
            GlobalDirectionConfig(confirmation_days=1))
        self.assertEqual(baseline.score.iloc[0], changed.score.iloc[0])


class OIExecutionTests(unittest.TestCase):
    def test_oi_oscillator_distinguishes_expansion_and_contraction(self):
        index = pd.date_range('2024-01-01', periods=80, freq='1D', tz='UTC')
        config = OIExecutionConfig()
        expanding = oi_oscillator(pd.Series(np.linspace(100, 200, 80), index=index), config)
        contracting = oi_oscillator(pd.Series(np.linspace(200, 100, 80), index=index), config)
        self.assertGreater(expanding.oi_oscillator_pct.iloc[-1], 0)
        self.assertLess(contracting.oi_oscillator_pct.iloc[-1], 0)

    def test_snapshot_supports_long_and_short_symmetrically(self):
        config = OIExecutionConfig(minimum_oi_oscillator_pct=0.0)
        length = 100
        index = pd.date_range('2024-01-01', periods=length, freq='1D', tz='UTC')
        funding = pd.Series(0.0, index=pd.date_range(
            index[0], index[-1] + pd.Timedelta(days=1), freq='8h'))
        oi = pd.Series(np.r_[
            np.linspace(1000, 1100, 90), np.linspace(1120, 1600, 10)
        ], index=index)

        long_close = np.linspace(100, 180, length)
        long_close[-3:] = [176, 175, 178]
        long_frame = _daily(long_close)
        long_frame.loc[index[-3:], 'low'] = long_frame.close.loc[index[-3:]] * 0.96
        long_snapshot = _asset_snapshot(
            long_frame, oi, funding, index[-1] + pd.Timedelta(days=1), 1, config)

        short_close = np.linspace(180, 100, length)
        short_close[-3:] = [104, 105, 102]
        short_frame = _daily(short_close)
        short_frame.loc[index[-3:], 'high'] = short_frame.close.loc[index[-3:]] * 1.04
        short_snapshot = _asset_snapshot(
            short_frame, oi, funding, index[-1] + pd.Timedelta(days=1), -1, config)

        self.assertTrue(long_snapshot['entry_ok'])
        self.assertTrue(short_snapshot['entry_ok'])


if __name__ == '__main__':
    unittest.main()
