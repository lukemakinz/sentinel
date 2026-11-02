import numpy as np
from django.test import SimpleTestCase

from backtest.run_s118_tf_robustness import benjamini_hochberg, simulate


class S118Test(SimpleTestCase):
    def test_simulate_returns_exit_offset(self):
        h = np.array([100.5, 101.0, 103.0]); l = np.array([99.5, 99.8, 100.5]); c = np.array([100.2, 100.8, 102.9])
        net, offset = simulate(1, 100.0, 99.0, h, l, c, 2.0, 3)
        self.assertEqual(offset, 2)
        self.assertAlmostEqual(net, 2.0 - (100 * 5 + 102 * 2) / 10_000, places=6)

    def test_simulate_no_target_time_exit(self):
        h = np.array([100.5, 100.6]); l = np.array([99.5, 99.6]); c = np.array([100.2, 100.4])
        net, offset = simulate(1, 100.0, 99.0, h, l, c, None, 2)
        self.assertEqual(offset, 1)
        self.assertLess(net, 0.4)

    def test_benjamini_hochberg(self):
        kept = benjamini_hochberg({'a': 0.001, 'b': 0.02, 'c': 0.5, 'd': 0.9}, q=0.10)
        self.assertEqual(kept, {'a', 'b'})
