from django.test import TestCase, override_settings

from executor.models import AccountState
from executor.paper_engine import PaperTradingEngine


class PaperEngineAccountStateTest(TestCase):
    @override_settings(INITIAL_BALANCE=100.0, PROFIT_TO_SPOT_RATIO=0.10)
    def test_profit_reserve_siphons_10pct_of_positive_pnl(self):
        engine = PaperTradingEngine()
        engine._update_account_state(20.0)

        state = AccountState.objects.order_by('-updated_at').first()
        self.assertAlmostEqual(state.balance, 118.0)
        self.assertAlmostEqual(state.spot_reserve_balance, 2.0)
        self.assertAlmostEqual(state.equity, 118.0)
