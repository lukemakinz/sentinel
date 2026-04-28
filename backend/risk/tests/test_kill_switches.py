"""DD-based size scaling replaces consecutive-loss logic."""
from django.test import TestCase, override_settings
from executor.models import AccountState
from risk.kill_switches import get_dd_size_multiplier, get_risk_state, check_kill_switches
from risk.models import RiskState


def make_account(balance, peak):
    AccountState.objects.create(
        balance=balance, equity=balance,
        peak_equity=peak, total_trades=0,
        winning_trades=0, losing_trades=0,
        total_pnl=0, max_drawdown=0,
    )


class DDBasedSizeMultiplierTest(TestCase):
    def test_no_drawdown_gives_full_size(self):
        make_account(10000, 10000)
        self.assertAlmostEqual(get_dd_size_multiplier(), 1.0)

    def test_5pct_dd_gives_75pct_size(self):
        make_account(9500, 10000)
        self.assertAlmostEqual(get_dd_size_multiplier(), 0.75)

    def test_10pct_dd_gives_50pct_size(self):
        make_account(9000, 10000)
        self.assertAlmostEqual(get_dd_size_multiplier(), 0.5)

    def test_15pct_dd_gives_25pct_size(self):
        make_account(8500, 10000)
        self.assertAlmostEqual(get_dd_size_multiplier(), 0.25)

    def test_20pct_dd_gives_halt(self):
        make_account(8000, 10000)
        self.assertAlmostEqual(get_dd_size_multiplier(), 0.0)

    def test_beyond_20pct_still_halts(self):
        make_account(7000, 10000)
        self.assertAlmostEqual(get_dd_size_multiplier(), 0.0)

    def test_no_account_state_defaults_to_full_size(self):
        # No AccountState in DB
        self.assertAlmostEqual(get_dd_size_multiplier(), 1.0)

    def test_3pct_dd_still_full_size(self):
        make_account(9700, 10000)
        self.assertAlmostEqual(get_dd_size_multiplier(), 1.0)

    @override_settings(MAX_DAILY_PORTFOLIO_DRAWDOWN=0.20)
    def test_daily_portfolio_equity_halt_triggers_at_20pct(self):
        AccountState.objects.create(
            balance=10000, equity=8000,
            peak_equity=10000, total_trades=0,
            winning_trades=0, losing_trades=0,
            total_pnl=0, max_drawdown=20,
        )
        RiskState.objects.create(
            pk=1,
            daily_start_equity=10000,
            daily_pnl=0,
            weekly_pnl=0,
            consecutive_losses=0,
            is_daily_stopped=False,
            is_weekly_stopped=False,
            position_size_multiplier=1.0,
            current_open_positions=0,
        )
        allowed, reason = check_kill_switches('BTCUSDT', 'LONG')
        self.assertFalse(allowed)
        self.assertIn('portfolio drawdown', reason.lower())
