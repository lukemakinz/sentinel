from unittest.mock import Mock

from django.test import TestCase

from executor.exchange_adapters import ExchangeOrderResult
from executor.live_execution import submit_protected_entry
from executor.models import ExchangeExecutionIntent


PARAMS = {
    'symbol': 'BTCUSDT',
    'side': 'LONG',
    'quantity': 0.0124,
    'stop_loss': 67000,
    'client_oid': 'sentinel-42',
    'strategy': 'S1',
}
PREPARED = {
    'request': {'clientOid': 'sentinel-42'},
    'submission': {
        'client_oid': 'sentinel-42',
        'symbol': 'BTCUSDT',
        'contract_symbol': 'XBTUSDTM',
        'side': 'LONG',
        'contracts': 12,
        'quantity_base': 0.012,
        'stop_loss': 67000,
        'strategy': 'S1',
    },
}


class LiveExecutionIntentTests(TestCase):
    def adapter(self):
        adapter = Mock()
        adapter.prepare_protected_order.return_value = ExchangeOrderResult(True, PREPARED)
        adapter.submit_prepared_protected_order.return_value = ExchangeOrderResult(True, {
            'code': '200000',
            'data': {'orderId': 'order-1', 'clientOid': 'sentinel-42'},
        })
        return adapter

    def test_intent_is_persisted_with_exact_rounded_size_before_submit_result(self):
        adapter = self.adapter()

        result = submit_protected_entry(adapter, PARAMS, signal_ref='consensus:42')

        self.assertTrue(result.ok)
        intent = ExchangeExecutionIntent.objects.get(client_oid='sentinel-42')
        self.assertEqual(intent.status, 'ACCEPTED')
        self.assertEqual(intent.order_id, 'order-1')
        self.assertEqual(intent.signal_ref, 'consensus:42')
        self.assertEqual(intent.requested_quantity, 0.0124)
        self.assertEqual(intent.submitted_quantity, 0.012)

    def test_retry_after_accepted_intent_never_posts_again(self):
        adapter = self.adapter()
        first = submit_protected_entry(adapter, PARAMS)
        second = submit_protected_entry(adapter, PARAMS)

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertTrue(second.payload['reused_execution_intent'])
        adapter.submit_prepared_protected_order.assert_called_once()

    def test_restart_recovers_prepared_intent_by_client_oid_without_post(self):
        adapter = self.adapter()
        ExchangeExecutionIntent.objects.create(
            client_oid='sentinel-42', symbol='BTCUSDT', side='LONG', strategy='S1',
            requested_quantity=0.0124, submitted_quantity=0.012, stop_loss=67000,
            status='PREPARED',
        )
        adapter.get_order_by_client_oid.return_value = ExchangeOrderResult(True, {
            'code': '200000',
            'data': {'id': 'order-1', 'clientOid': 'sentinel-42'},
        })

        result = submit_protected_entry(adapter, PARAMS)

        self.assertTrue(result.ok)
        self.assertTrue(result.payload['recovered_from_execution_intent'])
        adapter.submit_prepared_protected_order.assert_not_called()
        self.assertEqual(
            ExchangeExecutionIntent.objects.get(client_oid='sentinel-42').status,
            'ACCEPTED',
        )

    def test_unresolved_prepared_intent_fails_closed_without_post(self):
        adapter = self.adapter()
        ExchangeExecutionIntent.objects.create(
            client_oid='sentinel-42', symbol='BTCUSDT', side='LONG', strategy='S1',
            requested_quantity=0.0124, submitted_quantity=0.012, stop_loss=67000,
            status='PREPARED',
        )
        adapter.get_order_by_client_oid.return_value = ExchangeOrderResult(
            False, {'code': '404000'},
        )

        result = submit_protected_entry(adapter, PARAMS)

        self.assertFalse(result.ok)
        self.assertTrue(result.payload['manual_reconciliation_required'])
        adapter.submit_prepared_protected_order.assert_not_called()
        self.assertEqual(
            ExchangeExecutionIntent.objects.get(client_oid='sentinel-42').status,
            'UNCERTAIN',
        )

    def test_same_client_oid_cannot_describe_a_different_order(self):
        adapter = self.adapter()
        ExchangeExecutionIntent.objects.create(
            client_oid='sentinel-42', symbol='ETHUSDT', side='LONG', strategy='S1',
            requested_quantity=0.0124, submitted_quantity=0.012, stop_loss=67000,
            status='ACCEPTED',
        )

        result = submit_protected_entry(adapter, PARAMS)

        self.assertFalse(result.ok)
        self.assertIn('collision', result.payload['error'])
        self.assertTrue(result.payload['manual_reconciliation_required'])
        adapter.submit_prepared_protected_order.assert_not_called()

    def test_definitive_exchange_rejection_is_recorded(self):
        adapter = self.adapter()
        adapter.submit_prepared_protected_order.return_value = ExchangeOrderResult(
            False, {'code': '400100', 'msg': 'bad request'},
        )

        result = submit_protected_entry(adapter, PARAMS)

        self.assertFalse(result.ok)
        self.assertEqual(
            ExchangeExecutionIntent.objects.get(client_oid='sentinel-42').status,
            'REJECTED',
        )

    def test_second_active_intent_for_symbol_is_rejected_before_post(self):
        adapter = self.adapter()
        ExchangeExecutionIntent.objects.create(
            client_oid='existing-1', symbol='BTCUSDT', side='LONG', strategy='S1',
            requested_quantity=0.01, submitted_quantity=0.01, stop_loss=66000,
            status='OPEN',
        )

        result = submit_protected_entry(adapter, PARAMS)

        self.assertFalse(result.ok)
        self.assertIn('another active execution intent', result.payload['error'])
        self.assertEqual(result.payload['existing_client_oid'], 'existing-1')
        adapter.submit_prepared_protected_order.assert_not_called()
