import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import pandas as pd
import requests
from django.test import TestCase, override_settings

from backtest import bench_ab_r2_replay, paper_forward_ab
from backtest.paper_forward_ab import format_report, run_paper_forward, status_for


def fake_run(values):
    index = pd.date_range('2026-10-27', periods=len(values), freq='D', tz='UTC')
    daily = pd.Series(values, index=index)
    return {'daily': daily, 'daily_a': daily, 'daily_b': daily * 0, 'trades_b': 0}


class PaperForwardTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.override = override_settings(PAPER_FORWARD_DIR=self.tmp.name)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()

    def test_status_rules_follow_protocol(self):
        self.assertEqual(status_for({'max_drawdown_pct': 11, 'net_pnl': 5}, 90), 'BREACH_STOP')
        self.assertEqual(status_for({'max_drawdown_pct': 1, 'net_pnl': -1}, 10), 'INSUFFICIENT')
        self.assertEqual(status_for({'max_drawdown_pct': 1, 'net_pnl': -1}, 30), 'BELOW_EXPECTATION')
        self.assertEqual(status_for({'max_drawdown_pct': 1, 'net_pnl': 1}, 30), 'BELOW_EXPECTATION')
        self.assertEqual(status_for({'max_drawdown_pct': 1, 'net_pnl': 3}, 30), 'OBSERVE')
        self.assertEqual(status_for({
            'max_drawdown_pct': 1, 'net_pnl': 12, 'positive_month_share': 0.67,
        }, 90), 'ON_TRACK')
        self.assertEqual(status_for({
            'max_drawdown_pct': 1, 'net_pnl': 12, 'positive_month_share': 0.67,
        }, 90, {'2026-10-27': {}}), 'DATA_REVISED')

    def _run(self, values, end):
        with patch.object(paper_forward_ab, 'available_bounds',
                          return_value=(pd.Timestamp('2026-10-01', tz='UTC'), pd.Timestamp(end, tz='UTC'))), \
                patch.object(paper_forward_ab, 'load_market', return_value=({}, {}, {})), \
                patch.object(paper_forward_ab, 'book_b_signals', return_value={}), \
                patch.object(paper_forward_ab, 'replay', return_value=fake_run(values)):
            return run_paper_forward('/unused', now=pd.Timestamp(end, tz='UTC'))

    def test_nothing_scored_before_first_complete_day(self):
        report = self._run([], '2026-10-27')
        self.assertEqual(report['status'], 'NOT_STARTED')
        self.assertIn('brak pełnej doby', format_report(report))

    def test_ledger_and_revision_detection(self):
        first = self._run([1.0, -0.5], '2026-10-29')
        self.assertEqual(first['forward_days'], 2)
        self.assertEqual(first['revisions'], {})
        stored = json.loads(paper_forward_ab.ledger_path().read_text())
        self.assertEqual(stored['scenarios']['stress']['days']['total']['2026-10-27'], 1.0)

        second = self._run([1.2, -0.5, 0.3], '2026-10-30')
        self.assertEqual(list(second['revisions']), ['2026-10-27'])
        self.assertIn('zmienione dni', format_report(second))
        self.assertIn('DATA_REVISED', format_report(second))

    def test_unchanged_window_returns_ledger_without_replay(self):
        first = self._run([0.2], '2026-10-28')
        with patch.object(paper_forward_ab, 'available_bounds', return_value=(
                pd.Timestamp('2026-10-01', tz='UTC'),
                pd.Timestamp('2026-10-28', tz='UTC'))), \
                patch.object(paper_forward_ab, 'load_market') as load_market:
            second = run_paper_forward('/unused', now=pd.Timestamp('2026-10-28 12:00', tz='UTC'))
        self.assertEqual(second['computed_at'], first['computed_at'])
        self.assertTrue(second['unchanged'])
        load_market.assert_not_called()


class AvailableBoundsTests(TestCase):
    def test_uses_daily_archives_until_last_published_day(self):
        published = {'2026-09', '2026-10-25', '2026-10-26'}

        def fake(url):
            return any(f'-{key}.zip' in url for key in published)

        with patch.object(bench_ab_r2_replay, '_published', side_effect=fake):
            monthly_end, end = bench_ab_r2_replay.available_bounds(
                pd.Timestamp('2026-10-27 05:00', tz='UTC'))
        self.assertEqual(monthly_end, pd.Timestamp('2026-10-01', tz='UTC'))
        self.assertEqual(end, pd.Timestamp('2026-10-27', tz='UTC'))

        published.discard('2026-10-26')
        with patch.object(bench_ab_r2_replay, '_published', side_effect=fake):
            _, end = bench_ab_r2_replay.available_bounds(pd.Timestamp('2026-10-27 01:00', tz='UTC'))
        self.assertEqual(end, pd.Timestamp('2026-10-26', tz='UTC'))

    def test_uses_checksumed_cache_when_network_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            for symbol in bench_ab_r2_replay.SYMBOLS:
                for period, stamp in [('monthly', '2026-09'), ('daily', '2026-10-27')]:
                    if period == 'monthly':
                        root = Path(tmp) / 'klines' / symbol / '1m'
                    else:
                        root = Path(tmp) / 'daily' / 'klines' / symbol / '1m'
                    root.mkdir(parents=True, exist_ok=True)
                    archive = root / f'{symbol}-1m-{stamp}.zip'
                    archive.touch()
                    Path(f'{archive}.CHECKSUM').touch()

            with patch.object(bench_ab_r2_replay, '_published',
                              side_effect=bench_ab_r2_replay.ArchiveAvailabilityError('offline')):
                monthly_end, end = bench_ab_r2_replay.available_bounds(
                    pd.Timestamp('2026-10-29 05:00', tz='UTC'), tmp)

        self.assertEqual(monthly_end, pd.Timestamp('2026-10-01', tz='UTC'))
        self.assertEqual(end, pd.Timestamp('2026-10-28', tz='UTC'))

    def test_network_failure_is_not_reported_as_old_data(self):
        with patch.object(bench_ab_r2_replay, '_published',
                          side_effect=bench_ab_r2_replay.ArchiveAvailabilityError('offline')):
            with self.assertRaises(bench_ab_r2_replay.ArchiveAvailabilityError):
                bench_ab_r2_replay.available_bounds(
                    pd.Timestamp('2026-10-29 05:00', tz='UTC'))

    def test_probe_distinguishes_missing_archive_from_network_failure(self):
        response = type('Response', (), {'status_code': 404})()
        with patch('backtest.bench_ab_r2_replay.requests.head', return_value=response):
            self.assertFalse(bench_ab_r2_replay._published('https://example.test/missing.zip'))
        with patch('backtest.bench_ab_r2_replay.requests.head',
                   side_effect=requests.ConnectionError('offline')):
            with self.assertRaises(bench_ab_r2_replay.ArchiveAvailabilityError):
                bench_ab_r2_replay._published('https://example.test/archive.zip')
