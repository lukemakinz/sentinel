import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from backtest.dated_carry_data import (
    _fetch_continuous_rows,
    _parse_hourly_ohlc,
    _request_json,
    load_current_quarter_klines,
    load_dated_carry_market,
)


def kline(timestamp, open_=100, high=102, low=99, close=101):
    return [str(int(pd.Timestamp(timestamp).timestamp() * 1000)),
            str(open_), str(high), str(low), str(close), '10', '1000',
            '0', '0', '0', '0', '0']


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class DatedCarryDataTests(unittest.TestCase):
    def test_forward_pagination_advances_and_produces_complete_h1(self):
        session = Mock()
        session.get.side_effect = [
            FakeResponse([kline('2026-01-01 01:00Z'),
                          kline('2026-01-01 00:00Z')]),
            FakeResponse([kline('2026-01-01 02:00Z')]),
        ]
        start = pd.Timestamp('2026-01-01 00:00Z')
        end = pd.Timestamp('2026-01-01 03:00Z')
        rows = _fetch_continuous_rows('BTCUSDT', start, end, session)
        frame = _parse_hourly_ohlc(rows, start, end)
        self.assertEqual(len(frame), 3)
        self.assertTrue(frame.index.is_monotonic_increasing)
        first_start = session.get.call_args_list[0].kwargs['params']['startTime']
        second_start = session.get.call_args_list[1].kwargs['params']['startTime']
        self.assertGreater(second_start, first_start)
        self.assertEqual(
            session.get.call_args_list[0].kwargs['params']['contractType'],
            'CURRENT_QUARTER')

    @patch('backtest.dated_carry_data.time.sleep')
    def test_request_retries_transport_failure(self, sleep):
        session = Mock()
        session.get.side_effect = [
            requests.ConnectionError('temporary'), FakeResponse([])]
        self.assertEqual(
            _request_json(session, 'https://example.invalid', {}, retries=1), [])
        self.assertEqual(session.get.call_count, 2)
        sleep.assert_called_once()

    def test_cache_is_deterministic_offline_and_manifest_pins_sha256(self):
        start = pd.Timestamp('2026-01-01 00:00Z')
        end = pd.Timestamp('2026-01-01 02:00Z')
        # Deliberately reversed: cache creation must normalize API ordering.
        rows = [kline('2026-01-01 01:00Z'), kline('2026-01-01 00:00Z')]
        with TemporaryDirectory() as directory:
            with patch(
                    'backtest.dated_carry_data._fetch_continuous_rows',
                    return_value=rows):
                first, manifest = load_current_quarter_klines(
                    'BTCUSDT', start, end, directory,
                    download_missing=True, session=Mock())
            cache_path = Path(manifest[0]['cache_path'])
            payload = cache_path.read_bytes()
            self.assertEqual(
                manifest[0]['sha256'], hashlib.sha256(payload).hexdigest())
            document = json.loads(payload)
            self.assertEqual(document['contract_type'], 'CURRENT_QUARTER')
            self.assertEqual(
                [int(row[0]) for row in document['rows']],
                sorted(int(row[0]) for row in document['rows']))

            offline_session = Mock()
            second, second_manifest = load_current_quarter_klines(
                'BTCUSDT', start, end, directory,
                download_missing=False, session=offline_session)
            offline_session.get.assert_not_called()
            pd.testing.assert_frame_equal(first, second)
            self.assertEqual(
                manifest[0]['sha256'], second_manifest[0]['sha256'])

    def test_strict_h1_validation_rejects_gap_duplicate_and_bad_ohlc(self):
        start = pd.Timestamp('2026-01-01 00:00Z')
        end = pd.Timestamp('2026-01-01 02:00Z')
        with self.assertRaisesRegex(ValueError, 'exactly cover'):
            _parse_hourly_ohlc([kline(start)], start, end)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            _parse_hourly_ohlc([kline(start), kline(start)], start, end)
        with self.assertRaisesRegex(ValueError, 'OHLC'):
            _parse_hourly_ohlc([
                kline(start, high=100, close=101),
                kline(start + pd.Timedelta(hours=1)),
            ], start, end)

    @patch('backtest.dated_carry_data.load_current_quarter_klines')
    @patch('backtest.dated_carry_data._load_spot_archives')
    def test_combined_loader_uses_separate_verified_spot_cache(
            self, load_spot, load_quarterly):
        index = pd.date_range('2026-01-01', periods=2, freq='1h', tz='UTC')
        prices = pd.DataFrame({
            'open': [100.0, 101.0], 'high': [102.0, 103.0],
            'low': [99.0, 100.0], 'close': [101.0, 102.0],
        }, index=index)
        load_spot.return_value = (
            prices, [{'stream': 'spot', 'sha256': 'archive'}])
        load_quarterly.return_value = (
            prices, [{'stream': 'current_quarter', 'sha256': 'api'}])

        data, manifest = load_dated_carry_market(
            'ETHUSDT', '2026-01-01', '2026-01-01 02:00', '/api-cache',
            binance_cache='/archive-cache')

        self.assertEqual(set(data), {'spot', 'current_quarter'})
        self.assertEqual(
            [row['sha256'] for row in manifest], ['archive', 'api'])
        load_spot.assert_called_once_with(
            'ETHUSDT', pd.Timestamp('2026-01-01 00:00Z'),
            pd.Timestamp('2026-01-01 02:00Z'), '/archive-cache', False)
        load_quarterly.assert_called_once()

    def test_scope_is_limited_to_symbols_and_research_window(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            load_current_quarter_klines(
                'SOLUSDT', '2026-01-01', '2026-01-02', '/unused')
        with self.assertRaisesRegex(ValueError, 'within'):
            load_current_quarter_klines(
                'BTCUSDT', '2022-12-31', '2023-01-02', '/unused')


if __name__ == '__main__':
    unittest.main()
