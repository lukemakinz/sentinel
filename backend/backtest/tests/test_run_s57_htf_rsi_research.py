import unittest
from dataclasses import replace

from l1_filter.htf_extreme_reversion_scalp import (
    HTFExtremeReversionConfig,
    generate_htf_extreme_signals,
    htf_extreme_features,
)
from backtest.run_s57_htf_rsi_research import central_variants, execution_for


class S57ExecutionTests(unittest.TestCase):
    def test_two_frozen_payoff_shapes_on_rsi_extreme(self):
        names = [config.name for config, _ in central_variants()]
        self.assertEqual(names, ['S57_rsi_2p5_time', 'S57_rsi_patient_runner'])
        time_stop, runner = (execution_for(config, 'base') for config, _ in central_variants())
        self.assertEqual(time_stop.target_r, 2.5)
        self.assertFalse(time_stop.trailing)
        self.assertEqual(time_stop.max_hold_minutes, 2160)
        self.assertEqual(runner.target_r, 8.0)
        self.assertTrue(runner.trailing)
        self.assertEqual(runner.max_hold_minutes, 4320)

    def test_unknown_route_still_rejected_by_s40_config(self):
        with self.assertRaises(ValueError):
            HTFExtremeReversionConfig('x', 'not_a_route')
