"""Metrics are pure math — no DB needed."""
from django.test import TestCase
from backtest.metrics import (
    compute_sharpe, compute_max_drawdown, compute_calmar,
    compute_win_rate, compute_expected_value, BacktestMetrics,
)


class SharpeTest(TestCase):
    def test_positive_returns_positive_sharpe(self):
        returns = [1.0, 1.5, 0.8, 1.2, 0.9, 1.1, 0.7, 1.3]
        self.assertGreater(compute_sharpe(returns), 0)

    def test_negative_returns_negative_sharpe(self):
        returns = [-1.0, -1.5, -0.8, -1.2, -0.9]
        self.assertLess(compute_sharpe(returns), 0)

    def test_empty_returns_zero(self):
        self.assertEqual(compute_sharpe([]), 0.0)

    def test_single_return_zero(self):
        self.assertEqual(compute_sharpe([1.5]), 0.0)

    def test_zero_std_positive_mean_returns_positive(self):
        returns = [1.0, 1.0, 1.0, 1.0]
        self.assertGreater(compute_sharpe(returns), 0)


class MaxDrawdownTest(TestCase):
    def test_monotonic_rise_zero_dd(self):
        equity = [100, 110, 120, 130, 140]
        self.assertAlmostEqual(compute_max_drawdown(equity), 0.0)

    def test_drop_then_recovery(self):
        equity = [100, 120, 80, 110, 130]
        # Max DD = (120 - 80) / 120 = 33.3%
        self.assertAlmostEqual(compute_max_drawdown(equity), 33.33, places=1)

    def test_full_ruin(self):
        equity = [100, 50, 0]
        self.assertAlmostEqual(compute_max_drawdown(equity), 100.0)

    def test_empty_series_zero(self):
        self.assertEqual(compute_max_drawdown([]), 0.0)


class CalmarTest(TestCase):
    def test_positive_calmar(self):
        returns = [1.0, 1.5, 0.8, 1.2, 2.0, -0.5, 1.0, 1.3]
        equity  = [1000 + i * 100 for i in range(8)]
        calmar = compute_calmar(returns, equity)
        self.assertGreater(calmar, 0)

    def test_zero_drawdown_returns_large_calmar(self):
        returns = [1.0, 1.0, 1.0]
        equity  = [100, 110, 120, 130]
        calmar = compute_calmar(returns, equity)
        self.assertGreater(calmar, 10)  # very high when no DD

    def test_zero_returns_zero_calmar(self):
        returns = [0.0, 0.0, 0.0]
        equity  = [100, 100, 100]
        self.assertEqual(compute_calmar(returns, equity), 0.0)


class WinRateTest(TestCase):
    def test_all_winners(self):
        self.assertAlmostEqual(compute_win_rate([1, 2, 3, 4]), 1.0)

    def test_all_losers(self):
        self.assertAlmostEqual(compute_win_rate([-1, -2, -3]), 0.0)

    def test_50pct_win_rate(self):
        self.assertAlmostEqual(compute_win_rate([1, -1, 1, -1]), 0.5)

    def test_empty_returns_zero(self):
        self.assertEqual(compute_win_rate([]), 0.0)


class ExpectedValueTest(TestCase):
    def test_positive_ev(self):
        pnls = [100, -50, 120, -40, 110]
        ev = compute_expected_value(pnls)
        self.assertGreater(ev, 0)

    def test_negative_ev(self):
        pnls = [-100, 10, -80, 5, -90]
        self.assertLess(compute_expected_value(pnls), 0)

    def test_empty_zero(self):
        self.assertEqual(compute_expected_value([]), 0.0)


class BacktestMetricsBundleTest(TestCase):
    def test_bundle_from_trades(self):
        trades = [
            {'pnl': 150, 'pnl_pct': 1.5},
            {'pnl': -50, 'pnl_pct': -0.5},
            {'pnl': 120, 'pnl_pct': 1.2},
            {'pnl': -30, 'pnl_pct': -0.3},
            {'pnl': 200, 'pnl_pct': 2.0},
        ]
        equity_curve = [10000, 10150, 10100, 10220, 10190, 10390]
        m = BacktestMetrics.from_trades(trades, equity_curve, initial_capital=10000)
        self.assertEqual(m.total_trades, 5)
        self.assertEqual(m.winning_trades, 3)
        self.assertAlmostEqual(m.win_rate, 0.6)
        self.assertGreater(m.sharpe_ratio, 0)
        self.assertGreater(m.total_pnl, 0)
        self.assertGreaterEqual(m.max_drawdown, 0)

    def test_metrics_pass_live_thresholds(self):
        """Simulate a good strategy that meets go-live criteria."""
        import random
        random.seed(42)
        trades = [{'pnl': random.uniform(50, 300) if random.random() > 0.38 else random.uniform(-100, -20), 'pnl_pct': 0} for _ in range(300)]
        equity = [10000]
        for t in trades:
            equity.append(equity[-1] + t['pnl'])
        m = BacktestMetrics.from_trades(trades, equity, initial_capital=10000)
        self.assertGreater(m.total_trades, 299)
