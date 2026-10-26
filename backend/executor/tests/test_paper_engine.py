from django.test import TestCase, override_settings

from executor.models import AccountState, Position, Trade
from executor.paper_engine import PaperTradingEngine


EXECUTION_SETTINGS = dict(
    INITIAL_BALANCE=10_000.0,
    PROFIT_TO_SPOT_RATIO=0.0,
    PAPER_MARKET_SLIPPAGE_BPS=5.0,
    PAPER_ALT_SLIPPAGE_BPS=15.0,
    PAPER_TAKER_FEE_BPS=5.0,
    PAPER_MAKER_FEE_BPS=2.0,
    PAPER_STOP_MANAGEMENT_POLICY='INITIAL_STOP_ONLY',
)


def trade_params(*, side='LONG', order_type='MARKET', ratios=(0.25, 0.25, 0.50)):
    return {
        'symbol': 'BTCUSDT',
        'side': side,
        'entry_price': 100.0,
        'quantity': 10.0,
        'position_size_usd': 1000.0,
        'leverage': 2,
        'stop_loss': 99.0 if side == 'LONG' else 101.0,
        'take_profits': [
            {'level': 101.0 if side == 'LONG' else 99.0, 'ratio': ratios[0]},
            {'level': 102.0 if side == 'LONG' else 98.0, 'ratio': ratios[1]},
            {'level': None, 'ratio': ratios[2]},
        ],
        'order_type': order_type,
        'strategy': 'S1',
    }


class PaperEngineAccountStateTest(TestCase):
    @override_settings(INITIAL_BALANCE=100.0, PROFIT_TO_SPOT_RATIO=0.10)
    def test_profit_reserve_siphons_10pct_of_positive_pnl(self):
        engine = PaperTradingEngine()
        engine._update_account_state(20.0)

        state = AccountState.objects.order_by('-updated_at').first()
        self.assertAlmostEqual(state.balance, 118.0)
        self.assertAlmostEqual(state.spot_reserve_balance, 2.0)
        self.assertAlmostEqual(state.equity, 118.0)


@override_settings(**EXECUTION_SETTINGS)
class PaperEngineExecutionTruthTest(TestCase):
    def setUp(self):
        self.engine = PaperTradingEngine()

    def test_market_entry_is_adverse_and_charges_entry_fee(self):
        long = self.engine.open_position(trade_params(side='LONG'))
        short = self.engine.open_position(trade_params(side='SHORT'))

        self.assertAlmostEqual(long.entry_price, 100.05)
        self.assertAlmostEqual(short.entry_price, 99.95)
        self.assertAlmostEqual(long.realized_pnl, -(100.05 * 10 * 0.0005))
        self.assertLess(short.realized_pnl, 0)

    def test_market_exit_slippage_is_adverse_for_both_sides(self):
        long = self.engine.open_position(trade_params(side='LONG'))
        long_trade = self.engine._close_position(long, 101.0, 'TEST')
        short = self.engine.open_position(trade_params(side='SHORT'))
        short_trade = self.engine._close_position(short, 99.0, 'TEST')

        self.assertLess(long_trade.exit_price, 101.0)
        self.assertGreater(short_trade.exit_price, 99.0)
        self.assertLess(long_trade.pnl, 10.0)
        self.assertLess(short_trade.pnl, 10.0)

    def test_partial_target_uses_plan_ratio_and_charges_maker_fee(self):
        position = self.engine.open_position(
            trade_params(order_type='LIMIT', ratios=(0.25, 0.25, 0.50)))
        entry_cost = position.realized_pnl

        self.engine._check_sl_tp(position, {
            'open': 100.0, 'high': 101.2, 'low': 99.5, 'close': 101.0,
        })
        position.refresh_from_db()

        self.assertTrue(position.tp1_hit)
        self.assertAlmostEqual(position.remaining_quantity, 7.5)
        expected_partial = (101.0 - 100.0) * 2.5 - (101.0 * 2.5 * 0.0002)
        self.assertAlmostEqual(position.realized_pnl, entry_cost + expected_partial)

    def test_same_bar_stop_and_target_resolves_stop_first(self):
        position = self.engine.open_position(trade_params(order_type='LIMIT'))

        self.engine._check_sl_tp(position, {
            'open': 100.0, 'high': 102.0, 'low': 98.0, 'close': 101.0,
        })
        position.refresh_from_db()

        self.assertEqual(position.status, 'CLOSED')
        self.assertEqual(position.close_reason, 'STOP_LOSS')
        self.assertFalse(position.tp1_hit)
        self.assertEqual(Trade.objects.get().close_reason, 'STOP_LOSS')

    def test_initial_stop_policy_does_not_move_to_breakeven_after_tp1(self):
        position = self.engine.open_position(trade_params(order_type='LIMIT'))

        self.engine._check_sl_tp(position, {
            'open': 100.0, 'high': 101.2, 'low': 99.5, 'close': 101.0,
        })
        position.refresh_from_db()

        self.assertTrue(position.tp1_hit)
        self.assertFalse(position.sl_moved_to_be)
        self.assertEqual(position.stop_loss, 99.0)
