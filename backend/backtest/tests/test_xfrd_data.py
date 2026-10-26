import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from backtest.xfrd_data import (
    BYBIT_STREAMS,
    _fetch_bybit_rows,
    _parse_funding,
    _parse_klines,
    _request_json,
    load_binance_venue,
    load_bybit_venue,
)


UTC = 'UTC'


def kline(timestamp, open_=100, high=102, low=99, close=101):
    return [str(int(pd.Timestamp(timestamp).timestamp() * 1000)),
            str(open_), str(high), str(low), str(close), '10', '1000']


def funding(timestamp, rate='.0001', symbol='ETHUSDT'):
    return {
        'symbol': symbol,
        'fundingRate': rate,
        'fundingRateTimestamp': str(
            int(pd.Timestamp(timestamp).timestamp() * 1000)),
    }


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def response(rows):
    return FakeResponse({
        'retCode': 0,
        'retMsg': 'OK',
        'result': {'category': 'linear', 'list': rows},
    })


class XfrdDataTests(unittest.TestCase):
    def test_backward_pagination_produces_all_rows(self):
        session = Mock()
        session.get.side_effect = [
            response([kline('2026-01-01 02:00Z'),
                      kline('2026-01-01 01:00Z')]),
            response([kline('2026-01-01 00:00Z')]),
        ]
        rows = _fetch_bybit_rows(
            BYBIT_STREAMS['trade'], 'ETHUSDT',
            pd.Timestamp('2026-01-01 00:00Z'),
            pd.Timestamp('2026-01-01 03:00Z'), session)
        frame = _parse_klines(
            rows, 'trade', pd.Timestamp('2026-01-01 00:00Z'),
            pd.Timestamp('2026-01-01 03:00Z'))
        self.assertEqual(len(frame), 3)
        self.assertTrue(frame.index.is_monotonic_increasing)
        self.assertEqual(session.get.call_count, 2)
        first_end = session.get.call_args_list[0].kwargs['params']['end']
        second_end = session.get.call_args_list[1].kwargs['params']['end']
        self.assertLess(second_end, first_end)

    @patch('backtest.xfrd_data.time.sleep')
    def test_request_retries_transport_failure(self, sleep):
        session = Mock()
        session.get.side_effect = [
            requests.ConnectionError('temporary'), response([])]
        payload = _request_json(session, 'https://example.invalid', {}, retries=1)
        self.assertEqual(payload['retCode'], 0)
        self.assertEqual(session.get.call_count, 2)
        sleep.assert_called_once()

    def test_duplicate_kline_timestamp_is_rejected(self):
        rows = [kline('2026-01-01 00:00Z'), kline('2026-01-01 00:00Z')]
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            _parse_klines(
                rows, 'mark', pd.Timestamp('2026-01-01 00:00Z'),
                pd.Timestamp('2026-01-01 01:00Z'))

    def test_invalid_ohlc_is_rejected(self):
        rows = [kline('2026-01-01 00:00Z', open_=100,
                      high=100, low=99, close=101)]
        with self.assertRaisesRegex(ValueError, 'OHLC'):
            _parse_klines(
                rows, 'trade', pd.Timestamp('2026-01-01 00:00Z'),
                pd.Timestamp('2026-01-01 01:00Z'))

    def test_funding_is_sorted_and_duplicate_checked(self):
        series = _parse_funding([
            funding('2026-01-01 08:00Z'), funding('2026-01-01 00:00Z')],
            'ETHUSDT', pd.Timestamp('2026-01-01 00:00Z'),
            pd.Timestamp('2026-01-02 00:00Z'))
        self.assertTrue(series.index.is_monotonic_increasing)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            _parse_funding([
                funding('2026-01-01 00:00Z'),
                funding('2026-01-01 00:00Z')], 'ETHUSDT',
                pd.Timestamp('2026-01-01 00:00Z'),
                pd.Timestamp('2026-01-02 00:00Z'))

    def test_json_cache_is_offline_replayable_and_manifest_is_sha256(self):
        start = pd.Timestamp('2026-01-01 00:00Z')
        end = pd.Timestamp('2026-01-01 02:00Z')
        stream_rows = {
            'trade': [kline('2026-01-01 01:00Z'),
                      kline('2026-01-01 00:00Z')],
            'mark': [kline('2026-01-01 01:00Z'),
                     kline('2026-01-01 00:00Z')],
            'funding': [funding('2026-01-01 00:00Z')],
        }
        with TemporaryDirectory() as directory:
            with patch('backtest.xfrd_data._fetch_bybit_rows') as fetch:
                fetch.side_effect = lambda spec, *_args: stream_rows[spec.stream]
                first, manifest = load_bybit_venue(
                    'ETHUSDT', start, end, directory, download_missing=True,
                    session=Mock())
            self.assertEqual(set(first), {'trade', 'mark', 'funding'})
            self.assertEqual(len(manifest), 3)
            for entry in manifest:
                payload = Path(entry['cache_path']).read_bytes()
                self.assertEqual(entry['sha256'], hashlib.sha256(payload).hexdigest())
                self.assertEqual(json.loads(payload)['stream'], entry['stream'])

            offline_session = Mock()
            second, second_manifest = load_bybit_venue(
                'ETHUSDT', start, end, directory,
                download_missing=False, session=offline_session)
            offline_session.get.assert_not_called()
            pd.testing.assert_frame_equal(first['trade'], second['trade'])
            pd.testing.assert_series_equal(first['funding'], second['funding'])
            self.assertEqual(
                [row['sha256'] for row in manifest],
                [row['sha256'] for row in second_manifest])

    @patch('backtest.xfrd_data.load_fcm_archives')
    def test_binance_loader_maps_checksum_verified_fcm_shape(self, load_fcm):
        index = pd.date_range('2026-01-01', periods=24, freq='1h', tz=UTC)
        prices = pd.DataFrame({
            'open': [100.0] * 24, 'high': [101.0] * 24,
            'low': [99.0] * 24, 'close': [100.5] * 24,
        }, index=index)
        rates = pd.Series([.0001] * 24, index=index)
        load_fcm.return_value = ({
            'spot': prices,
            'perpetual': prices,
            'mark': prices,
            'funding': rates,
        }, [
            {'stream': 'spot', 'sha256': 'spot'},
            {'stream': 'perpetual', 'sha256': 'trade'},
            {'stream': 'mark', 'sha256': 'mark'},
            {'stream': 'funding', 'sha256': 'funding'},
        ])
        data, manifest = load_binance_venue(
            'ETHUSDT', '2026-01-01', '2026-01-02', '/cache')
        self.assertEqual(set(data), {'trade', 'mark', 'funding'})
        self.assertIs(data['trade'], prices)
        self.assertEqual(
            [row['stream'] for row in manifest],
            ['trade', 'mark', 'funding'])
        load_fcm.assert_called_once()


if __name__ == '__main__':
    unittest.main()
