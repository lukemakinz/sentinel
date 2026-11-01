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
            # Freeze within the setup's resolution horizon. Using wall-clock
            # time makes this test expire as the calendar advances.
            self.assertEqual(resolve_open(now=pd.Timestamp('2026-10-27 00:00', tz='UTC')), [])
        self.assertEqual(sorted(calls), ['XUSDT', 'YUSDT'])
        self.assertEqual(SetupObservation.objects.filter(outcome='OPEN').count(), 2)


class SetupVariantTests(TestCase):
    def _obs(self):
        row = {**setup_row(), 'first_bsl_min_3r': 104.0,
               'features': {'fvg_mid': 99.5, 'mss_close': 101.0}}
        record_scan({'rows': [row]})
        return SetupObservation.objects.get()

    def test_entry_and_exit_variants_on_the_same_path(self):
        from l1_filter.setup_journal import resolve_variants

        # Dips to 99.4 (fills edge 100 and mid 99.5), rallies through 102 (2R
        # from 100) and 104 (target); never touches the 99 stop.
        path = bars([(101, 101, 99.4, 100.2), (100.2, 102.5, 100.0, 102.2), (102.2, 104.3, 102, 104)])
        variants = resolve_variants(path, self._obs())

        self.assertEqual(variants['fvg_edge+tp1']['outcome'], 'TARGET')
        self.assertAlmostEqual(variants['fvg_edge+tp1']['net_r'], 3.2366, places=3)
        # Mid entry has a tighter stop, so the same target is worth more R.
        self.assertGreater(variants['fvg_mid+tp1']['net_r'], variants['fvg_edge+tp1']['net_r'])
        # Market entry at the first open (101) after MSS: 2R stop distance -> fewer R.
        self.assertLess(variants['mss_market+tp1']['net_r'], variants['fvg_edge+tp1']['net_r'])
        partial = variants['fvg_edge+ext3r_partial2r']
        self.assertEqual(partial['outcome'], 'TARGET')
        self.assertLess(partial['net_r'], variants['fvg_edge+ext3r']['net_r'])

    def test_partial_then_stop_keeps_half_of_the_2r(self):
        from l1_filter.setup_journal import resolve_variant

        path = bars([(101, 101, 99.9, 100.5), (100.5, 102.1, 100.2, 101), (101, 101, 98.5, 99)])
        result = resolve_variant(path, self._obs(), 'fvg_edge', 'ext3r_partial2r')
        self.assertEqual(result['outcome'], 'STOPPED')
        # Half at 2R gross = 0.5 x 1.542R net under stress costs, half stopped at -1R.
        self.assertAlmostEqual(result['net_r'], 0.271, places=3)


class SetupFeatureFreezeTests(TestCase):
    def test_first_seen_features_survive_later_scans(self):
        first = {**setup_row(), 'features': {'btc_above_ema50_1h': True}}
        record_scan({'rows': [first]})
        obs = SetupObservation.objects.get()
        obs.payload = {**obs.payload, 'variants': {'fvg_edge+tp1': {'outcome': 'OPEN'}}}
        obs.save(update_fields=['payload'])

        later = {**setup_row('IN_POSITION'), 'features': {'btc_above_ema50_1h': False}}
        record_scan({'rows': [later]})
        obs.refresh_from_db()

        self.assertTrue(obs.payload['features']['btc_above_ema50_1h'])
        self.assertIn('variants', obs.payload)
        self.assertEqual(obs.last_status, 'IN_POSITION')
