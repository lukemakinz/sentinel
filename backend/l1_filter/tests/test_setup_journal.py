import pandas as pd
from django.test import TestCase

from l1_filter.models import SetupObservation
from l1_filter.setup_journal import journal_summary, record_scan, resolve_path

MSS = '2026-10-26 10:00:00+00:00'
SWEEP = '2026-10-26 09:15:00+00:00'


def setup_row(status='WAIT_RETEST', rr_ok=True):
    return {
        'symbol': 'XUSDT', 'side': 'LONG', 'status': status, 'score': 6,
        'mss_time': MSS, 'sweep_time': SWEEP, 'entry_limit': 100.0,
        'stop_loss': 99.0, 'tp1_bsl': 104.0, 'rr_tp1_net_stress': 3.24,
        'checklist': {'rr_tp1_min_1_3': rr_ok}, 'absorption': 'oi_flush',
        'next': 'Czekaj na retest',
    }


def bars(rows, start='2026-10-26 10:15'):
    index = pd.date_range(start, periods=len(rows), freq='15min', tz='UTC')
    return pd.DataFrame(rows, columns=['open', 'high', 'low', 'close'], index=index)


class SetupJournalTests(TestCase):
    def test_record_is_idempotent_and_marks_episode_reached_mss(self):
        episode = {'symbol': 'XUSDT', 'side': 'LONG', 'status': 'WAIT_MSS', 'score': 3,
                   'sweep_time': SWEEP, 'next': 'Czekaj na MSS'}
        self.assertEqual(len(record_scan({'rows': [episode]})), 1)
        self.assertEqual(len(record_scan({'rows': [setup_row()]})), 1)
        self.assertEqual(len(record_scan({'rows': [setup_row('IN_POSITION')]})), 0)

        setup = SetupObservation.objects.get(kind='SETUP')
        self.assertEqual(setup.first_status, 'WAIT_RETEST')
        self.assertEqual(setup.last_status, 'IN_POSITION')
        self.assertEqual(SetupObservation.objects.get(kind='EPISODE').outcome, 'MSS')

    def _obs(self):
        record_scan({'rows': [setup_row()]})
        return SetupObservation.objects.get()

    def test_fill_then_tp1_scores_stress_net_r(self):
        result = resolve_path(bars([(101, 101, 99.9, 100.5), (100.5, 104.2, 100.2, 104)]), self._obs())
        self.assertEqual(result['outcome'], 'TP1_HIT')
        self.assertAlmostEqual(result['net_r'], 3.2366, places=3)

    def test_stop_on_fill_bar_counts_as_loss(self):
        result = resolve_path(bars([(101, 101, 98.5, 99)]), self._obs())
        self.assertEqual((result['outcome'], result['net_r']), ('STOPPED', -1.0))

    def test_unfilled_limit_expires_after_ttl(self):
        rows = [(102, 103, 101, 102)] * 18
        self.assertEqual(resolve_path(bars(rows), self._obs())['outcome'], 'EXPIRED')

    def test_summary_separates_strict_rr(self):
        record_scan({'rows': [setup_row()]})
        other = dict(setup_row(rr_ok=False), symbol='YUSDT')
        record_scan({'rows': [other]})
        SetupObservation.objects.filter(symbol='XUSDT').update(outcome='TP1_HIT', net_r=3.2)
        SetupObservation.objects.filter(symbol='YUSDT').update(outcome='STOPPED', net_r=-1.0)
        summary = journal_summary()

        self.assertEqual(summary['strict_rr_1_3']['filled_closed'], 1)
        self.assertEqual(summary['all_setups_to_tp1']['total_net_r'], 2.2)


class SetupJournalNetworkTests(TestCase):
    def test_network_error_leaves_rows_open_and_continues(self):
        from unittest.mock import patch

        import requests

        from l1_filter.setup_journal import resolve_open

        record_scan({'rows': [setup_row(), dict(setup_row(), symbol='YUSDT')]})
        calls = []

        def flaky(session, path, params):
            calls.append(params['symbol'])
            raise requests.ConnectionError('offline')

        with patch('l1_filter.setup_journal._get', side_effect=flaky):
            self.assertEqual(resolve_open(), [])
        self.assertEqual(sorted(calls), ['XUSDT', 'YUSDT'])
        self.assertEqual(SetupObservation.objects.filter(outcome='OPEN').count(), 2)
