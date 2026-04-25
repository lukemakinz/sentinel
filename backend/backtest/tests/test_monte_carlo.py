"""Monte Carlo permutation tests."""
from django.test import TestCase
from backtest.monte_carlo import run_monte_carlo, MonteCarloResult


class MonteCarloTest(TestCase):
    def test_profitable_strategy_low_ruin_probability(self):
        # 60% WR, avg win 2R, avg loss 1R → strongly positive EV
        pnls = [200] * 60 + [-100] * 40
        result = run_monte_carlo(pnls, n_simulations=1000, initial_capital=10000)
        self.assertIsInstance(result, MonteCarloResult)
        self.assertLess(result.ruin_probability, 0.10)  # < 10% ruin

    def test_losing_strategy_high_ruin_probability(self):
        pnls = [-200] * 70 + [100] * 30
        result = run_monte_carlo(pnls, n_simulations=1000, initial_capital=10000)
        self.assertGreater(result.ruin_probability, 0.50)

    def test_result_has_required_fields(self):
        pnls = [100, -50, 120, -40, 80] * 20
        result = run_monte_carlo(pnls, n_simulations=500, initial_capital=10000)
        self.assertIsNotNone(result.median_final_capital)
        self.assertIsNotNone(result.worst_5pct_drawdown)
        self.assertIsNotNone(result.ruin_probability)
        self.assertIsNotNone(result.median_sharpe)

    def test_empty_trades_returns_zero_ruin(self):
        result = run_monte_carlo([], n_simulations=100, initial_capital=10000)
        self.assertEqual(result.ruin_probability, 0.0)
        self.assertEqual(result.total_simulations, 0)

    def test_n_simulations_respected(self):
        pnls = [100, -50] * 50
        result = run_monte_carlo(pnls, n_simulations=200, initial_capital=10000)
        self.assertEqual(result.total_simulations, 200)
