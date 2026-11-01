import numpy as np
from django.test import SimpleTestCase

from backtest.run_s117_exit_geometry import simulate_exit


class SimulateExitTest(SimpleTestCase):
    def run_exit(self, highs, lows, closes, target=2.0, direction=1, hold=10):
        return simulate_exit(direction, 100.0, 1.0, np.array(highs, float), np.array(lows, float),
                             np.array(closes, float), target, hold, slip=0.0)

    def test_target_hit_is_maker_without_slippage(self):
        r = self.run_exit([100.5, 102.1], [99.5, 100.5], [100.2, 102.0])
        self.assertAlmostEqual(r, 2.0 - (100 * 5 + 102 * 2) / 10_000, places=6)

    def test_same_bar_stop_first(self):
        r = self.run_exit([102.5], [98.9], [100.0])
        self.assertAlmostEqual(r, -1.0 - (100 * 5 + 99 * 5) / 10_000, places=6)

    def test_time_exit_at_last_close_of_hold(self):
        r = self.run_exit([100.5, 100.6, 105], [99.6, 99.7, 99.8], [100.3, 100.5, 104], hold=2)
        self.assertAlmostEqual(r, 0.5 - (100 * 5 + 100.5 * 5) / 10_000, places=6)

    def test_short_mirror_and_no_target(self):
        r = self.run_exit([100.2, 100.1], [99.0, 97.0], [99.5, 97.5], target=None, direction=-1, hold=2)
        self.assertAlmostEqual(r, 2.5 - (100 * 5 + 97.5 * 5) / 10_000, places=6)
