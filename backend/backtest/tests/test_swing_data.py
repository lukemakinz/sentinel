import unittest
from io import StringIO

import numpy as np
import pandas as pd

from backtest.swing_data import (
    _read_archive_csv,
    _timestamps,
    regularize_interval,
    validate_interval,
)


def _frame(index):
    rows = len(index)
    return pd.DataFrame({
        'open': np.full(rows, 100.0),
        'high': np.full(rows, 101.0),
        'low': np.full(rows, 99.0),
        'close': np.full(rows, 100.0),
        'volume': np.full(rows, 10.0),
        'taker_buy_volume': np.full(rows, 5.0),
    }, index=index)


class SwingDataTests(unittest.TestCase):
    def test_archive_parser_preserves_first_old_headerless_kline(self):
        rows = (
            '1609459200000,100,101,99,100,10,1609459499999,1000,2,5,500,0\n'
            '1609459500000,100,101,99,100,10,1609459799999,1000,2,5,500,0\n')
        parsed = _read_archive_csv(StringIO(rows), 'klines')
        self.assertEqual(len(parsed), 2)
        self.assertEqual(int(parsed.timestamp.iloc[0]), 1609459200000)

    def test_archive_parser_drops_only_optional_text_header(self):
        rows = (
            'open_time,open,high,low,close,volume,close_time,quote_volume,count,'
            'taker_buy_volume,taker_buy_quote_volume,ignore\n'
            '1735689600000,100,101,99,100,10,1735689899999,1000,2,5,500,0\n')
        parsed = _read_archive_csv(StringIO(rows), 'klines')
        self.assertEqual(len(parsed), 1)
        self.assertEqual(int(parsed.timestamp.iloc[0]), 1735689600000)

    def test_timestamp_parser_returns_floorable_utc_index_for_csv_series(self):
        source = pd.Series([1_735_689_600_123, 1_735_689_900_456])
        parsed = pd.DatetimeIndex(_timestamps(source)).floor('min')
        self.assertEqual(str(parsed.tz), 'UTC')
        self.assertEqual(parsed[0], pd.Timestamp('2025-01-01 00:00Z'))

    def test_validate_interval_accepts_complete_five_minute_data(self):
        validate_interval(_frame(pd.date_range(
            '2025-01-01', periods=3, freq='5min', tz='UTC')), minutes=5)

    def test_validate_interval_rejects_gap(self):
        frame = _frame(pd.DatetimeIndex([
            '2025-01-01 00:00Z', '2025-01-01 00:10Z']))
        with self.assertRaisesRegex(ValueError, 'Missing 5m bars'):
            validate_interval(frame, minutes=5)

    def test_allow_gaps_then_regularize_uses_only_prior_close(self):
        index = pd.DatetimeIndex([
            '2025-01-01 00:00Z', '2025-01-01 00:10Z'])
        frame = _frame(index)
        frame.loc[index[0], 'close'] = 99.5
        validate_interval(frame, minutes=5, allow_gaps=True)
        result = regularize_interval(
            frame, index[0], index[-1] + pd.Timedelta(minutes=5), minutes=5)
        missing = result.loc[pd.Timestamp('2025-01-01 00:05Z')]
        self.assertTrue(missing.synthetic)
        self.assertEqual(missing.open, 99.5)
        self.assertEqual(missing.high, 99.5)
        self.assertEqual(missing.low, 99.5)
        self.assertEqual(missing.close, 99.5)
        self.assertEqual(missing.volume, 0.0)

    def test_regularize_refuses_leading_gap_without_causal_price(self):
        frame = _frame(pd.DatetimeIndex(['2025-01-01 00:05Z']))
        with self.assertRaisesRegex(ValueError, 'leading execution gap'):
            regularize_interval(
                frame, '2025-01-01 00:00Z', '2025-01-01 00:10Z', minutes=5)


if __name__ == '__main__':
    unittest.main()
