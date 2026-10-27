import json
import tempfile
from unittest.mock import patch

import pandas as pd
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
        self.assertEqual(status_for({'max_drawdown_pct': 1, 'net_pnl': 1}, 30), 'ON_TRACK')

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
        self.assertIn('INSUFFICIENT', format_report(second))


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
