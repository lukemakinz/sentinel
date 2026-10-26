import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from backtest.funding_carry_data import KLINE_COLUMNS
from backtest.s35_data import required_s35_archive_specs
from backtest.s36_data import (
    OHLC_COLUMNS,
    PERPETUAL_COLUMNS,
    _load_price_stream,
    load_s36_symbol,
    load_s36_universe,
    required_s36_archive_specs,
    s36_archive_spec,
)


def raw_klines(times, *, gap_at=None):
    rows = []
    for number, timestamp in enumerate(times):
        if timestamp == gap_at:
            continue
        open_ = 100 + number
        close = open_ + 0.5
        rows.append([
            int(timestamp.timestamp() * 1000),
            open_, close + 0.5, open_ - 1, close,
            10 + number,
            int((timestamp + pd.Timedelta(minutes=5)).timestamp() * 1000) - 1,
            1000 + number,
            5 + number,
            4 + number / 10,
            400 + number,
            0,
        ])
    return pd.DataFrame(rows, columns=range(len(KLINE_COLUMNS)))


def market_fixture(index):
    ohlc = pd.DataFrame({
        'open': [100.] * len(index),
        'high': [101.] * len(index),
        'low': [99.] * len(index),
        'close': [100.5] * len(index),
    }, index=index)
    perpetual = ohlc.assign(
        volume=[10.] * len(index),
        quote_volume=[1000.] * len(index),
        num_trades=np.array([5] * len(index), dtype=np.int64),
        taker_buy_volume=[4.] * len(index),
        taker_buy_quote_volume=[400.] * len(index),
    )
    return {
        'perpetual': perpetual,
        'mark': ohlc.copy(),
        'index': ohlc.copy(),
        'funding': pd.Series([0.0001], index=index[:1]),
    }


class S36DataTests(unittest.TestCase):
    def setUp(self):
        self.start = pd.Timestamp('2025-01-01 00:00Z')
        self.end = pd.Timestamp('2025-01-01 00:20Z')
        self.times = pd.date_range(
            self.start, self.end, freq='5min', inclusive='left')
        self.perpetual_spec = s36_archive_spec(
            'ETHUSDT', '2025-01', 'perpetual')

    def test_archive_contract_is_identical_to_s35(self):
        s35 = required_s35_archive_specs(
            'ETHUSDT', self.start, self.end)
        s36 = required_s36_archive_specs(
            'ETHUSDT', self.start, self.end)
        self.assertEqual(s36, s35)
        self.assertEqual(
            s36_archive_spec('DOGEUSDT', '2025-01', 'perpetual'),
            next(spec for spec in required_s35_archive_specs(
                'DOGEUSDT', self.start, self.end)
                 if spec.stream == 'perpetual'))

    @patch('backtest.s36_data._read_csv')
    def test_perpetual_retains_complete_trade_flow_schema(self, read_csv):
        read_csv.return_value = raw_klines(self.times)
        frame, coverage = _load_price_stream(
            [self.perpetual_spec], '/unused', self.start, self.end,
            'perpetual')

        self.assertEqual(tuple(frame.columns), PERPETUAL_COLUMNS)
        self.assertTrue(pd.api.types.is_integer_dtype(frame.num_trades.dtype))
        self.assertEqual(frame.num_trades.tolist(), [5, 6, 7, 8])
        self.assertEqual(frame.taker_buy_volume.tolist(), [4., 4.1, 4.2, 4.3])
        self.assertEqual(
            frame.taker_buy_quote_volume.tolist(), [400., 401., 402., 403.])
        expected_delta = (
            2 * frame.taker_buy_quote_volume - frame.quote_volume
        ) / frame.quote_volume
        self.assertAlmostEqual(expected_delta.iloc[0], -0.2)
        self.assertEqual(coverage['missing_5m_bars_from_first_observation'], 0)

    @patch('backtest.s36_data._read_csv')
    def test_mark_and_index_do_not_gain_perpetual_only_fields(self, read_csv):
        read_csv.return_value = raw_klines(self.times)
        for stream in ('mark', 'index'):
            with self.subTest(stream=stream):
                spec = s36_archive_spec('ETHUSDT', '2025-01', stream)
                frame, _ = _load_price_stream(
                    [spec], '/unused', self.start, self.end, stream)
                self.assertEqual(tuple(frame.columns), OHLC_COLUMNS)

    @patch('backtest.s36_data._read_csv')
    def test_gap_is_preserved_and_reported(self, read_csv):
        missing = self.times[1]
        read_csv.return_value = raw_klines(self.times, gap_at=missing)
        frame, coverage = _load_price_stream(
            [self.perpetual_spec], '/unused', self.start, self.end,
            'perpetual')
        self.assertNotIn(missing, frame.index)
        self.assertEqual(len(frame), 3)
        self.assertEqual(coverage['missing_5m_bars_from_first_observation'], 1)
        self.assertIn(missing.isoformat(), coverage['first_missing_5m'])

    @patch('backtest.s36_data._read_csv')
    def test_malformed_archive_schema_is_a_hard_failure(self, read_csv):
        read_csv.return_value = raw_klines(self.times).iloc[:, :-1]
        with self.assertRaisesRegex(ValueError, 'kline schema'):
            _load_price_stream(
                [self.perpetual_spec], '/unused', self.start, self.end,
                'perpetual')

    @patch('backtest.s36_data._read_csv')
    def test_duplicate_and_off_grid_timestamps_are_hard_failures(self, read_csv):
        duplicate = raw_klines([self.times[0], self.times[0]])
        read_csv.return_value = duplicate
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            _load_price_stream(
                [self.perpetual_spec], '/unused', self.start, self.end,
                'perpetual')

        off_grid = raw_klines([self.times[0] + pd.Timedelta(minutes=1)])
        read_csv.return_value = off_grid
        with self.assertRaisesRegex(ValueError, '5m'):
            _load_price_stream(
                [self.perpetual_spec], '/unused', self.start, self.end,
                'perpetual')

    @patch('backtest.s36_data._read_csv')
    def test_invalid_trade_flow_values_are_hard_failures(self, read_csv):
        cases = {
            'negative trade count': (8, -1, 'trade-flow'),
            'fractional trade count': (8, 1.5, 'integers'),
            'negative taker volume': (9, -0.1, 'trade-flow'),
            'taker base above total': (9, 10.1, 'exceeds'),
            'taker quote above total': (10, 1000.1, 'exceeds'),
        }
        for name, (column, value, error) in cases.items():
            with self.subTest(case=name):
                raw = raw_klines(self.times).astype(float)
                raw.iloc[0, column] = value
                read_csv.return_value = raw
                with self.assertRaisesRegex(ValueError, error):
                    _load_price_stream(
                        [self.perpetual_spec], '/unused',
                        self.start, self.end, 'perpetual')

    @patch('backtest.s36_data._read_csv')
    def test_invalid_ohlc_is_a_hard_failure(self, read_csv):
        raw = raw_klines(self.times)
        raw.iloc[0, 2] = raw.iloc[0, 1] - 1
        read_csv.return_value = raw
        with self.assertRaisesRegex(ValueError, 'OHLC'):
            _load_price_stream(
                [self.perpetual_spec], '/unused', self.start, self.end,
                'perpetual')

    @patch('backtest.s36_data._load_funding_stream')
    @patch('backtest.s36_data._load_price_stream')
    @patch('backtest.s36_data.prepare_archives')
    def test_symbol_manifest_discloses_s36_extension(
            self, prepare, load_price, load_funding):
        specs = required_s36_archive_specs(
            'ETHUSDT', self.start, self.end)
        prepare.return_value = [
            {'stream': spec.stream, 'sha256': f'hash-{number}'}
            for number, spec in enumerate(specs)
        ]
        market = market_fixture(self.times)
        load_price.side_effect = lambda _specs, _cache, _start, _end, stream: (
            market[stream], {'rows': len(market[stream])})
        load_funding.return_value = (
            market['funding'], {'rows': len(market['funding'])})

        loaded, manifest = load_s36_symbol(
            'ETHUSDT', self.start, self.end, '/unused')

        self.assertEqual(set(loaded), {'perpetual', 'mark', 'index', 'funding'})
        self.assertEqual(
            tuple(manifest['perpetual_columns']), PERPETUAL_COLUMNS)
        self.assertIn('taker_buy_quote_volume', manifest['order_flow_proxy'])
        self.assertEqual(len(manifest['archives']), 4)
        self.assertTrue(all(
            row['relative_cache_path'].startswith('futures/')
            for row in manifest['archives']))
        prepare.assert_called_once_with(
            specs, '/unused', download_missing=False, workers=8)

    @patch('backtest.s36_data.load_s36_symbol')
    def test_universe_shape_order_and_privacy_contract(self, load_symbol):
        market = market_fixture(self.times)
        load_symbol.side_effect = lambda symbol, *_args, **_kwargs: (
            market, {'symbol': symbol})
        symbols = ['SUIUSDT', 'DOGEUSDT', 'XRPUSDT', 'SOLUSDT', 'ETHUSDT']
        markets, manifest = load_s36_universe(
            symbols, self.start, self.end, '/unused')
        self.assertEqual(list(markets), symbols)
        self.assertEqual(tuple(
            markets['DOGEUSDT']['perpetual'].columns), PERPETUAL_COLUMNS)
        self.assertTrue(manifest['no_api_key_or_account_data'])
        self.assertIn('no interpolation', manifest['missing_policy'])
        self.assertEqual(load_symbol.call_count, 5)

    def test_universe_rejects_duplicates_unknowns_and_off_grid_ranges(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            load_s36_universe(
                ['ETHUSDT', 'ETHUSDT'], self.start, self.end, '/unused')
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            load_s36_universe(
                ['BTCUSDT'], self.start, self.end, '/unused')
        with self.assertRaisesRegex(ValueError, '5m'):
            required_s36_archive_specs(
                'ETHUSDT', '2025-01-01 00:01Z', self.end)


if __name__ == '__main__':
    unittest.main()
