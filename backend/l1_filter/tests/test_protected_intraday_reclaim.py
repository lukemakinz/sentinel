import unittest

from l1_filter.protected_intraday_reclaim import ProtectedIntradayReclaimConfig


class ProtectedIntradayReclaimTests(unittest.TestCase):
    def test_execution_activates_ratchet_without_partial_exit(self):
        execution = ProtectedIntradayReclaimConfig().execution()
        self.assertTrue(execution.trailing)
        self.assertTrue(execution.dollar_ratchet)
        self.assertEqual(execution.partial_r, 0.25)
        self.assertEqual(execution.partial_fraction, 0.0)
        self.assertEqual(execution.dollar_ratchet_lock_fraction, 0.5)


if __name__ == '__main__':
    unittest.main()
