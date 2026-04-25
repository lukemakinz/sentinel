"""Strategy Monitor — rolling Sharpe, auto-halt."""
from datetime import datetime, timezone, timedelta
from django.test import TestCase
from executor.models import Trade
from risk.strategy_monitor import check_strategy_health, compute_rolling_sharpe


def make_trade(pnl_pct, minutes_ago=0):
    t = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    Trade.objects.create(
        symbol='BTCUSDT', side='LONG',
        entry_price=90000, exit_price=90000 * (1 + pnl_pct / 100),
        quantity=0.01, position_size_usd=900,
        pnl=900 * pnl_pct / 100, pnl_percent=pnl_pct,
        entry_time=t - timedelta(minutes=30), exit_time=t,
        duration_minutes=30,
    )


class StrategyMonitorHealthTest(TestCase):
    def test_insufficient_trades_returns_ok(self):
        for _ in range(5):
            make_trade(1.0)
        ok, reason = check_strategy_health()
        self.assertTrue(ok)
        self.assertIn('insufficient', reason.lower())

    def test_profitable_strategy_is_healthy(self):
        for i in range(30):
            make_trade(1.5 if i % 2 == 0 else -0.5)
        ok, _ = check_strategy_health()
        self.assertTrue(ok)

    def test_20_consecutive_losing_trades_halts(self):
        # First 10: profitable (to set baseline)
        for i in range(10):
            make_trade(2.0, minutes_ago=300 + i * 10)
        # Last 20: all losers → rolling Sharpe < 0
        for i in range(20):
            make_trade(-1.0, minutes_ago=i * 10)
        ok, reason = check_strategy_health()
        self.assertFalse(ok)
        self.assertIn('degraded', reason.lower())

    def test_mixed_trades_positive_sharpe_is_healthy(self):
        returns = [2.0, 1.5, -0.5, 1.8, 2.1, -0.8, 1.6, 2.0, -0.3, 1.9] * 3
        for i, r in enumerate(returns):
            make_trade(r, minutes_ago=i * 15)
        ok, _ = check_strategy_health()
        self.assertTrue(ok)


class ComputeRollingSharpeTest(TestCase):
    def test_all_positive_returns_positive_sharpe(self):
        returns = [1.0, 1.5, 0.8, 1.2, 0.9]
        sharpe = compute_rolling_sharpe(returns)
        self.assertGreater(sharpe, 0)

    def test_all_negative_returns_negative_sharpe(self):
        returns = [-1.0, -1.5, -0.8, -1.2, -0.9]
        sharpe = compute_rolling_sharpe(returns)
        self.assertLess(sharpe, 0)

    def test_zero_std_positive_returns_positive(self):
        returns = [1.0, 1.0, 1.0]
        sharpe = compute_rolling_sharpe(returns)
        self.assertGreater(sharpe, 0)

    def test_zero_std_negative_returns_negative(self):
        returns = [-1.0, -1.0, -1.0]
        sharpe = compute_rolling_sharpe(returns)
        self.assertLess(sharpe, 0)

    def test_empty_returns_zero(self):
        sharpe = compute_rolling_sharpe([])
        self.assertEqual(sharpe, 0.0)
