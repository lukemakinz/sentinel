import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from backtest.funding_carry_data import KLINE_COLUMNS
from backtest.s35_data import (
    LISTING_UTC,
    SUPPORTED_SYMBOLS,
    _load_funding_stream,
    _load_price_stream,
    load_s35_universe,
    required_s35_archive_specs,
    s35_archive_spec,
)


def raw_klines(times, *, gap_at=None, invalid_high=False):
    rows = []
    for number, timestamp in enumerate(times):
        if timestamp == gap_at:
            continue
        open_ = 100 + number
        close = open_ + 0.5
        high = open_ if invalid_high else close + 0.5
        rows.append([
            int(timestamp.timestamp() * 1000), open_, high, open_ - 1,
            close, 10, int((timestamp + pd.Timedelta(minutes=5)).timestamp()
                           * 1000) - 1,
            1000, 5, 4, 400, 0,
        ])
    return pd.DataFrame(rows, columns=range(len(KLINE_COLUMNS)))


def raw_funding(times, rates=None):
    rates = rates or [0.0001] * len(times)
    return pd.DataFrame({
        'calc_time': [int(timestamp.timestamp() * 1000) for timestamp in times],
        'last_funding_rate': rates,
    })


class S35DataTests(unittest.TestCase):
    def test_frozen_universe_and_archive_paths(self):
        self.assertEqual(
            set(SUPPORTED_SYMBOLS),
            {'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'SUIUSDT'})
        index = s35_archive_spec('ETHUSDT', '2025-01', 'index')
        self.assertIn(
            'indexPriceKlines/ETHUSDT/5m/ETHUSDT-5m-2025-01.zip',
            index.relative)
        funding = s35_archive_spec('ETHUSDT', '2025-01', 'funding')
        self.assertIn(
            'fundingRate/ETHUSDT/ETHUSDT-fundingRate-2025-01.zip',
            funding.relative)

    def test_pre_listing_months_are_not_requested(self):
        specs = required_s35_archive_specs(
            'SUIUSDT', '2021-07-01', '2023-06-01')
        self.assertEqual({spec.month for spec in specs}, {'2023-05'})
        self.assertEqual(len(specs), 4)
        with self.assertRaisesRegex(ValueError, 'not listed'):
            required_s35_archive_specs(
                'SUIUSDT', '2021-07-01', LISTING_UTC['SUIUSDT'])

    @patch('backtest.s35_data._read_csv')
    def test_price_gap_is_preserved_and_reported_not_filled(self, read_csv):
        start = pd.Timestamp('2025-01-01 00:00Z')
        end = pd.Timestamp('2025-01-01 00:20Z')
        times = pd.date_range(start, end, freq='5min', inclusive='left')
        missing = times[1]
        read_csv.return_value = raw_klines(times, gap_at=missing)
        spec = s35_archive_spec('ETHUSDT', '2025-01', 'perpetual')
        frame, quality = _load_price_stream(
            [spec], '/unused', start, end, 'perpetual')
        self.assertNotIn(missing, frame.index)
        self.assertEqual(len(frame), 3)
        self.assertEqual(quality['missing_5m_bars_from_first_observation'], 1)
        self.assertNotIn('freq', frame.attrs)

    @patch('backtest.s35_data._read_csv')
    def test_duplicate_and_invalid_ohlc_are_hard_failures(self, read_csv):
        start = pd.Timestamp('2025-01-01 00:00Z')
        end = pd.Timestamp('2025-01-01 00:10Z')
        times = pd.date_range(start, end, freq='5min', inclusive='left')
        spec = s35_archive_spec('ETHUSDT', '2025-01', 'mark')
        duplicate = raw_klines([times[0], times[0]])
        read_csv.return_value = duplicate
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            _load_price_stream([spec], '/unused', start, end, 'mark')
        read_csv.return_value = raw_klines(times, invalid_high=True)
        with self.assertRaisesRegex(ValueError, 'OHLC'):
            _load_price_stream([spec], '/unused', start, end, 'mark')

    @patch('backtest.s35_data._read_csv')
    def test_funding_timestamp_uses_causal_ceiling_and_audits_raw(self, read_csv):
        start = pd.Timestamp('2025-01-01 00:00Z')
        end = pd.Timestamp('2025-01-01 09:00Z')
        raw_time = pd.Timestamp('2025-01-01 08:00:00.001Z')
        read_csv.return_value = raw_funding([raw_time])
        spec = s35_archive_spec('ETHUSDT', '2025-01', 'funding')
        rates, audit = _load_funding_stream(
            [spec], '/unused', start, end)
        self.assertEqual(rates.index[0], pd.Timestamp('2025-01-01 08:05Z'))
        self.assertEqual(audit['adjusted_timestamp_count_all_loaded_months'], 1)
        self.assertEqual(
            audit['timestamp_adjustments_first_20'][0]['raw_calc_time'],
            raw_time.isoformat())
        self.assertIn('never floor', audit['signal_timestamp_rule'])

    @patch('backtest.s35_data._read_csv')
    def test_duplicate_after_funding_ceiling_is_rejected(self, read_csv):
        start = pd.Timestamp('2025-01-01 00:00Z')
        end = pd.Timestamp('2025-01-01 09:00Z')
        read_csv.return_value = raw_funding([
            pd.Timestamp('2025-01-01 08:00:00.001Z'),
            pd.Timestamp('2025-01-01 08:04:59.999Z'),
        ])
        spec = s35_archive_spec('ETHUSDT', '2025-01', 'funding')
        with self.assertRaisesRegex(ValueError, 'after causal ceil'):
            _load_funding_stream([spec], '/unused', start, end)

    @patch('backtest.s35_data.load_s35_symbol')
    def test_universe_shape_matches_simulator_contract(self, load_symbol):
        index = pd.date_range('2025-01-01', periods=2, freq='5min', tz='UTC')
        ohlc = pd.DataFrame({
            'open': [1., 1.], 'high': [1., 1.],
            'low': [1., 1.], 'close': [1., 1.],
        }, index=index)
        market = {
            'perpetual': ohlc.assign(
                volume=[10., 11.], quote_volume=[1000., 1100.]),
            'mark': ohlc,
            'index': ohlc,
            'funding': pd.Series([0.0001], index=index[:1]),
        }
        load_symbol.side_effect = lambda symbol, *_args, **_kwargs: (
            market, {'symbol': symbol})
        symbols = ['ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'SUIUSDT']
        markets, manifest = load_s35_universe(
            symbols, '2025-01-01', '2025-01-02', '/unused')
        self.assertEqual(list(markets), symbols)
        self.assertEqual(
            set(markets['SUIUSDT']), {'perpetual', 'mark', 'index', 'funding'})
        self.assertTrue(manifest['no_api_key_or_account_data'])
        self.assertIn('no interpolation', manifest['missing_policy'])
        self.assertEqual(load_symbol.call_count, 5)

    def test_request_validation_rejects_duplicates_and_off_grid(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            load_s35_universe(
                ['ETHUSDT', 'ETHUSDT'], '2025-01-01', '2025-01-02',
                '/unused')
        with self.assertRaisesRegex(ValueError, '5m'):
            required_s35_archive_specs(
                'ETHUSDT', '2025-01-01 00:01', '2025-01-02')


if __name__ == '__main__':
    unittest.main()
