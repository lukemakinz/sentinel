from unittest.mock import patch

from django.test import TestCase, override_settings

from l1_filter.tasks import scan_all_symbols
from l2_agents.models import L2Decision


AI_CONTEXT = {
    'symbol': 'ETHUSDT',
    'direction': 'LONG',
    'strategy': 'S12AI',
    'shadow_only': True,
    'ai_candidate': {
        'passed_count': 6,
        'total_count': 9,
        'setup_fingerprint': 'same-event',
    },
}


@override_settings(AI_ADJUDICATOR_SHADOW_ENABLED=True)
class AIScanRoutingTests(TestCase):
    @patch('l2_agents.tasks.run_l2_analysis.delay')
    @patch('django.core.cache.cache.add', return_value=True)
    @patch('l1_filter.scanner.L1Scanner.scan', side_effect=[None, AI_CONTEXT])
    @patch('ingester.models.WatchedPair.get_active_symbols', return_value=['ETHUSDT'])
    def test_quorum_candidate_is_sent_to_shadow_l2_once(self, _pairs, _scan, _lock, delay):
        result = scan_all_symbols()
        delay.assert_called_once_with(AI_CONTEXT)
        self.assertEqual(result['ETHUSDT'], 'FAIL')

    @patch('l2_agents.tasks.run_l2_analysis.delay')
    @patch('django.core.cache.cache.add', return_value=True)
    @patch('l1_filter.scanner.L1Scanner.scan', side_effect=[None, AI_CONTEXT])
    @patch('ingester.models.WatchedPair.get_active_symbols', return_value=['ETHUSDT'])
    def test_same_structural_event_is_not_sent_twice(self, _pairs, _scan, _lock, delay):
        L2Decision.objects.create(
            symbol='ETHUSDT', direction='LONG', action='REJECT', dismissed=True,
            trade_context=AI_CONTEXT,
        )
        scan_all_symbols()
        delay.assert_not_called()

    @patch('l2_agents.tasks.run_l2_analysis.delay')
    @patch('django.core.cache.cache.add', return_value=False)
    @patch('l1_filter.scanner.L1Scanner.scan', side_effect=[None, AI_CONTEXT])
    @patch('ingester.models.WatchedPair.get_active_symbols', return_value=['ETHUSDT'])
    def test_atomic_queue_lock_suppresses_overlapping_scan(
            self, _pairs, _scan, _lock, delay):
        scan_all_symbols()
        delay.assert_not_called()
