"""News Calendar — blocks trading 2h before high-impact events."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from django.test import TestCase
from risk.news_calendar import is_news_blackout, get_next_event


class NewsBlackoutTest(TestCase):
    def _now(self, dt_str):
        return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)

    def test_2h_before_event_is_blocked(self):
        # Pretend a FOMC is at 2026-06-18 19:00 UTC
        # 90 minutes before = 17:30 → blocked
        fake_now = self._now('2026-06-18T17:30:00')
        with patch('risk.news_calendar.get_events_today', return_value=[
            {'name': 'FOMC', 'datetime': self._now('2026-06-18T19:00:00')}
        ]):
            self.assertTrue(is_news_blackout(fake_now))

    def test_1h_after_event_is_blocked(self):
        fake_now = self._now('2026-06-18T19:45:00')
        with patch('risk.news_calendar.get_events_today', return_value=[
            {'name': 'FOMC', 'datetime': self._now('2026-06-18T19:00:00')}
        ]):
            self.assertTrue(is_news_blackout(fake_now))

    def test_3h_before_event_is_clear(self):
        fake_now = self._now('2026-06-18T16:00:00')
        with patch('risk.news_calendar.get_events_today', return_value=[
            {'name': 'FOMC', 'datetime': self._now('2026-06-18T19:00:00')}
        ]):
            self.assertFalse(is_news_blackout(fake_now))

    def test_2h_after_event_is_clear(self):
        fake_now = self._now('2026-06-18T21:30:00')
        with patch('risk.news_calendar.get_events_today', return_value=[
            {'name': 'FOMC', 'datetime': self._now('2026-06-18T19:00:00')}
        ]):
            self.assertFalse(is_news_blackout(fake_now))

    def test_no_events_today_is_clear(self):
        fake_now = self._now('2026-06-18T12:00:00')
        with patch('risk.news_calendar.get_events_today', return_value=[]):
            self.assertFalse(is_news_blackout(fake_now))

    def test_blackout_window_is_2h_before_1h_after(self):
        event_time = self._now('2026-06-18T19:00:00')
        with patch('risk.news_calendar.get_events_today', return_value=[
            {'name': 'CPI', 'datetime': event_time}
        ]):
            # 2h before: blocked
            self.assertTrue(is_news_blackout(self._now('2026-06-18T17:01:00')))
            # exactly 2h before: blocked
            self.assertTrue(is_news_blackout(self._now('2026-06-18T17:00:00')))
            # 1h after: blocked
            self.assertTrue(is_news_blackout(self._now('2026-06-18T19:59:00')))
            # 1h after: boundary
            self.assertFalse(is_news_blackout(self._now('2026-06-18T20:01:00')))
