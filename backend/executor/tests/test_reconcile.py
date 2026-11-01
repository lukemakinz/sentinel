from django.test import TestCase

from executor.reconcile import halt_on_mismatch, protective_stop_mismatches, reconcile
from risk.trading_state import current


class ReconcileTests(TestCase):
    def test_every_kind_of_difference_is_reported(self):
        local = [{'symbol': 'A', 'side': 'LONG', 'quantity': 1.0},
                 {'symbol': 'B', 'side': 'LONG', 'quantity': 1.0},
                 {'symbol': 'C', 'side': 'SHORT', 'quantity': 1.0},
                 {'symbol': 'OK', 'side': 'LONG', 'quantity': 1.0}]
        exchange = [{'symbol': 'B', 'side': 'SHORT', 'quantity_base': 1.0},
                    {'symbol': 'C', 'side': 'SHORT', 'quantity_base': 1.5},
                    {'symbol': 'D', 'side': 'LONG', 'quantity_base': 2.0},
                    {'symbol': 'OK', 'side': 'LONG', 'quantity_base': 1.01}]
        issues = {m['symbol']: m['issue'] for m in reconcile(local, exchange)}
        self.assertEqual(issues, {'A': 'MISSING_ON_EXCHANGE', 'B': 'SIDE_MISMATCH',
                                  'C': 'SIZE_MISMATCH', 'D': 'UNKNOWN_ON_EXCHANGE'})

    def test_mismatch_halts_with_manual_unlock(self):
        self.assertFalse(halt_on_mismatch([]))
        self.assertTrue(halt_on_mismatch([{'symbol': 'D', 'issue': 'UNKNOWN_ON_EXCHANGE'}]))
        state = current()
        self.assertEqual((state.state, state.manual_unlock), ('HALT', True))

    def test_pending_entry_order_is_not_a_missing_position(self):
        local = [{
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity': 0.012,
            'client_oid': 'entry-1', 'status': 'ACCEPTED',
        }]
        self.assertEqual(
            reconcile(local, [], pending_client_oids={'entry-1'}),
            [],
        )

    def test_closing_intent_allows_position_to_disappear(self):
        local = [{
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity': 0.012,
            'client_oid': 'entry-1', 'status': 'CLOSING',
        }]
        self.assertEqual(reconcile(local, []), [])

    def test_protection_requires_adverse_reduce_only_stop(self):
        position = [{
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity_base': 0.01,
            'entry_price': 68000,
        }]
        unsafe = [{
            'symbol': 'BTCUSDT', 'side': 'SHORT', 'status': 'open',
            'is_active': True, 'reduce_only': False, 'close_order': False,
            'stop_direction': 'down', 'stop_price': 67000,
        }]
        safe = [{**unsafe[0], 'reduce_only': True}]

        self.assertEqual(
            protective_stop_mismatches(position, unsafe, stop_orders_ok=True)[0]['issue'],
            'UNPROTECTED_ON_EXCHANGE',
        )
        self.assertEqual(
            protective_stop_mismatches(position, safe, stop_orders_ok=True),
            [],
        )

    def test_stop_inventory_failure_is_a_mismatch_when_position_open(self):
        position = [{
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity_base': 0.01,
            'entry_price': 68000,
        }]
        result = protective_stop_mismatches(position, [], stop_orders_ok=False)
        self.assertEqual(result[0]['issue'], 'STOP_ORDER_SYNC_FAILED')
