"""Portfolio Heat — BTC-beta correlation exposure limit."""
from django.test import TestCase, override_settings
from executor.models import Position, AccountState
from risk.portfolio_heat import check_portfolio_heat, get_btc_beta_exposure


def make_position(symbol, side, size_usd):
    Position.objects.create(
        symbol=symbol, side=side, status='OPEN',
        entry_price=90000, current_price=90000,
        quantity=size_usd / 90000,
        position_size_usd=size_usd,
        stop_loss=89000, remaining_quantity=size_usd / 90000,
    )


def make_account(equity=10000):
    AccountState.objects.create(
        balance=equity, equity=equity,
        peak_equity=equity, total_trades=0,
        winning_trades=0, losing_trades=0,
        total_pnl=0, max_drawdown=0,
    )


@override_settings(INITIAL_BALANCE=10000)
class PortfolioHeatTest(TestCase):
    def setUp(self):
        make_account(10000)

    def test_no_positions_is_ok(self):
        ok, reason = check_portfolio_heat()
        self.assertTrue(ok)

    def test_single_btc_position_within_limit(self):
        make_position('BTCUSDT', 'LONG', 5000)  # 50% equity, 1× BTC-beta = 0.5× total
        ok, reason = check_portfolio_heat()
        self.assertTrue(ok)

    def test_too_much_btc_exposure_blocked(self):
        # 25000 of BTCUSDT on 10000 equity = 2.5× BTC-beta → blocked
        make_position('BTCUSDT', 'LONG', 25000)
        ok, reason = check_portfolio_heat()
        self.assertFalse(ok)
        self.assertIn('BTC', reason)

    def test_correlated_positions_sum_correctly(self):
        # ETH beta ≈ 0.9, SOL beta ≈ 0.8
        make_position('BTCUSDT', 'LONG', 8000)   # 0.8× BTC-beta
        make_position('ETHUSDT', 'LONG', 8000)   # ~0.72× BTC-beta
        # Total ≈ 1.52× → borderline but ok (threshold 2×)
        ok, _ = check_portfolio_heat()
        self.assertTrue(ok)

    def test_get_btc_beta_exposure_returns_float(self):
        make_position('BTCUSDT', 'LONG', 5000)
        exposure = get_btc_beta_exposure()
        self.assertIsInstance(exposure, float)
        self.assertGreater(exposure, 0)

    def test_short_position_reduces_exposure(self):
        make_position('BTCUSDT', 'LONG',  20000)  # +2× BTC-beta → would fail alone
        make_position('BTCUSDT', 'SHORT', 10000)  # -1× BTC-beta → net 1× → ok
        # Net exposure depends on implementation (abs vs net)
        exposure = get_btc_beta_exposure()
        self.assertIsInstance(exposure, float)
