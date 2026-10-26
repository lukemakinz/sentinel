import unittest

from backtest.run_s64_day_swing_research import (
    calendar_day_pnl,
    evaluate_development_gate,
    evaluate_validation_gate,
)


class S64GateTests(unittest.TestCase):
    def test_ten_dollars_a_day_over_ten_days_hits_goal(self):
        mean, days = calendar_day_pnl(100.0, '2025-05-01', '2025-05-11')
        self.assertEqual(days, 10)
        self.assertEqual(mean, 10.0)

    def test_development_gate_requires_trades_profit_and_pf(self):
        self.assertFalse(evaluate_development_gate(
            {'trades': 19, 'net_pnl': 1.0, 'profit_factor': 1.2}))
        self.assertTrue(evaluate_development_gate(
            {'trades': 20, 'net_pnl': 1.0, 'profit_factor': 1.06}))

    def test_validation_gate_requires_stress_survival(self):
        self.assertFalse(evaluate_validation_gate({
            'base': {'trades': 12, 'profit_factor': 1.2},
            'stress': {'profit_factor': 0.9},
        }))
        self.assertTrue(evaluate_validation_gate({
            'base': {'trades': 12, 'profit_factor': 1.2},
            'stress': {'profit_factor': 1.0},
        }))
