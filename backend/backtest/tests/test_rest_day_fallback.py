import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd
from django.test import SimpleTestCase

from backtest import scalp_data


def kline(open_ms):
    return [open_ms, '1', '2', '0.5', '1.5', '10', open_ms + 59_999, '15', 3, '5', '7', '0']


class RestDayFallbackTest(SimpleTestCase):
    def _session(self, minutes):
        start = int(pd.Timestamp('2026-10-28', tz='UTC').value // 10**6)
        rows = [kline(start + i * 60_000) for i in range(minutes)]
        pages = [rows[:1500], rows[1500:], []]
        session = MagicMock()
        session.get.side_effect = [
            MagicMock(json=MagicMock(return_value=page), raise_for_status=MagicMock())
            for page in pages
        ]
        return session

    def test_unpublished_daily_archive_falls_back_to_complete_rest_day(self):
        missing = MagicMock(status_code=404)
        with tempfile.TemporaryDirectory() as cache, \
                patch.object(scalp_data, '_get_with_read_retries', return_value=missing), \
                patch.object(scalp_data.requests, 'Session', return_value=self._session(1440)):
            frame, source = scalp_data._daily_kline_archive('BTCUSDT', '2026-10-28', cache)
            # Cached: a second read makes no network calls.
            with patch.object(scalp_data.requests, 'Session', side_effect=AssertionError):
                again, _ = scalp_data._daily_kline_archive('BTCUSDT', '2026-10-28', cache)
        self.assertEqual(len(frame), 1440)
        self.assertEqual(source['source'], 'rest_fallback_no_daily_archive')
        self.assertTrue(frame.equals(again))

    def test_incomplete_rest_day_is_rejected(self):
        with tempfile.TemporaryDirectory() as cache:
            with self.assertRaises(scalp_data.MissingMarketDataError):
                scalp_data._rest_day_klines('BTCUSDT', '2026-10-28', cache,
                                            session=self._session(1439))
