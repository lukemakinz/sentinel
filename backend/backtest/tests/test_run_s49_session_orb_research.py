import importlib.util
import unittest

from l1_filter.session_orb_scalp import SessionORBConfig
from backtest.run_s49_session_orb_research import (
    central_variants,
    evaluate_development_gate,
    evaluate_validation_gate,
)


class S49RunnerTests(unittest.TestCase):
    def test_runner_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec(
            'backtest.run_s49_session_orb_research'))

    def test_two_frozen_clock_session_routes(self):
        routes = [config.route for config in central_variants()]
        self.assertEqual(
            routes, ['utc_open_with_trend', 'london_with_trend'])

    def test_execution_is_early_profit_not_trailing(self):
        for config in central_variants():
            execution = config.execution()
            self.assertFalse(execution.trailing)
            self.assertEqual(execution.target_r, 1.0)
            self.assertEqual(execution.max_hold_minutes, 90)

    def test_development_gate_rejects_negative_expectancy(self):
        failing = {'trades': 40, 'net_pnl': -1.0, 'profit_factor': 0.9}
        passing = {'trades': 40, 'net_pnl': 2.0, 'profit_factor': 1.2}
        self.assertFalse(evaluate_development_gate(failing))
        self.assertTrue(evaluate_development_gate(passing))

    def test_validation_gate_requires_stress_survival(self):
        failing = {
            'base': {'trades': 20, 'profit_factor': 1.2},
            'stress': {'trades': 18, 'profit_factor': 0.9},
        }
        passing = {
            'base': {'trades': 20, 'profit_factor': 1.2},
            'stress': {'trades': 18, 'profit_factor': 1.05},
        }
        self.assertFalse(evaluate_validation_gate(failing))
        self.assertTrue(evaluate_validation_gate(passing))

    def test_unknown_route_is_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            SessionORBConfig(route='grid_search_forbidden')
