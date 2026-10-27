from django.test import TestCase

from executor.reconcile import halt_on_mismatch, reconcile
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
