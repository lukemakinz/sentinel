from unittest.mock import patch

from django.test import TestCase, override_settings

from executor.exchange_adapters import ExchangeOrderResult
from executor.models import (
    AccountState,
    ExchangeClosedOrder,
    ExchangeExecutionIntent,
    ExchangeFill,
    ExchangeOpenOrder,
    Position,
)
from executor.tasks import (
    force_close_all,
    monitor_positions,
    sync_live_exchange_state,
    transfer_profit_reserve_to_spot,
)


class ExecutorTaskTest(TestCase):
    @override_settings(
        LIVE_TRADING_ENABLED=True, PROFIT_TO_SPOT_RATIO=0.10,
        LIVE_CAPITAL_BASELINE_USD=100.0,
    )
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_transfer_profit_reserve_uses_ratio_when_amount_missing(self, mock_get_adapter):
        adapter = mock_get_adapter.return_value
        adapter.transfer_profit_to_spot.return_value = ExchangeOrderResult(False, {'error': 'not implemented'})
        AccountState.objects.create(balance=150.0, equity=150.0, peak_equity=150.0)

        result = transfer_profit_reserve_to_spot()

        self.assertEqual(result['amount_usd'], 5.0)
        adapter.transfer_profit_to_spot.assert_called_once_with(5.0)

    @override_settings(
        LIVE_TRADING_ENABLED=True, PROFIT_TO_SPOT_RATIO=0.10,
        LIVE_CAPITAL_BASELINE_USD=100.0,
    )
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_successful_profit_reserve_cannot_be_repeatedly_drained(self, mock_get_adapter):
        adapter = mock_get_adapter.return_value
        adapter.transfer_profit_to_spot.return_value = ExchangeOrderResult(True, {'ok': True})
        state = AccountState.objects.create(
            balance=150.0, equity=150.0, peak_equity=150.0,
        )

        first = transfer_profit_reserve_to_spot()
        second = transfer_profit_reserve_to_spot()
        state.refresh_from_db()

        self.assertTrue(first['ok'])
        self.assertEqual(second['reason'], 'no_unreserved_profit')
        self.assertEqual(state.balance, 145.0)
        self.assertEqual(state.spot_reserve_balance, 5.0)
        adapter.transfer_profit_to_spot.assert_called_once_with(5.0)

    @patch('executor.paper_engine.PaperTradingEngine._update_position_price')
    def test_monitor_positions_never_touches_exchange_mirror(self, update_price):
        paper = Position.objects.create(
            symbol='ETHUSDT', side='LONG', entry_price=100, current_price=100,
            quantity=1, remaining_quantity=1, position_size_usd=100,
            stop_loss=90, source='paper',
        )
        Position.objects.create(
            symbol='BTCUSDT', side='LONG', entry_price=100, current_price=100,
            quantity=1, remaining_quantity=1, position_size_usd=100,
            stop_loss=90, source='exchange',
        )
        update_price.return_value = None

        result = monitor_positions()

        update_price.assert_called_once_with(paper)
        self.assertEqual(result['exchange_open_untouched'], 1)

    def test_eod_exchange_position_is_not_fake_closed_and_halts(self):
        from risk.trading_state import current

        exchange = Position.objects.create(
            symbol='BTCUSDT', side='LONG', entry_price=100, current_price=100,
            quantity=1, remaining_quantity=1, position_size_usd=100,
            stop_loss=90, source='exchange',
        )

        result = force_close_all()
        exchange.refresh_from_db()

        self.assertEqual(exchange.status, 'OPEN')
        self.assertEqual(result['exchange_open_untouched'], 1)
        self.assertEqual(current().state, 'HALT')

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_eod_exchange_position_submits_reduce_only_close_without_fake_close(
        self, mock_get_adapter,
    ):
        from risk.trading_state import current

        adapter = mock_get_adapter.return_value
        adapter.close_position.return_value = ExchangeOrderResult(
            True, {'code': '200000', 'data': {'orderId': 'close-1'}},
        )
        exchange = Position.objects.create(
            symbol='BTCUSDT', side='LONG', entry_price=100, current_price=100,
            quantity=0.012, remaining_quantity=0.012, position_size_usd=1.2,
            stop_loss=90, leverage=3, source='exchange',
        )

        result = force_close_all()
        exchange.refresh_from_db()

        self.assertEqual(exchange.status, 'OPEN')
        self.assertEqual(result['exchange_close_submitted'], 1)
        self.assertEqual(result['exchange_open_untouched'], 0)
        self.assertEqual(current().state, 'NORMAL')
        adapter.close_position.assert_called_once_with({
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity': 0.012,
            'leverage': 3, 'margin_mode': 'isolated',
            'client_oid': f'sentinel-eod-{exchange.id}',
        })

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_sync_live_exchange_state_reads_overview_and_positions(self, mock_get_adapter):
        adapter = mock_get_adapter.return_value
        adapter.get_account_overview.return_value = ExchangeOrderResult(True, {'code': '200000', 'data': {'availableBalance': 123}})
        adapter.get_positions.return_value = ExchangeOrderResult(True, {'code': '200000', 'data': [{'symbol': 'XBTUSDTM'}]})
        adapter.get_open_orders.return_value = ExchangeOrderResult(True, {'code': '200000', 'data': {'items': []}})
        adapter.get_stop_orders.return_value = ExchangeOrderResult(True, {'code': '200000', 'data': {'items': []}})
        adapter.get_recent_fills.return_value = ExchangeOrderResult(True, {'code': '200000', 'data': [{'tradeId': 'fill-1'}]})
        adapter.get_recent_closed_orders.return_value = ExchangeOrderResult(True, {'code': '200000', 'data': [{'id': 'done-1'}]})
        adapter.normalize_positions.return_value = [{
            'symbol': 'BTCUSDT',
            'side': 'LONG',
            'quantity_contracts': 12,
            'quantity_base': 0.012,
            'entry_price': 68000.0,
            'mark_price': 68500.0,
            'position_size_usd': 816.0,
            'unrealized_pnl': 6.5,
            'margin_mode': 'isolated',
            'leverage': 10,
        }]
        adapter.normalize_open_orders.return_value = [{
            'order_id': 'order-1',
            'client_oid': 'client-1',
            'symbol': 'ETHUSDT',
            'side': 'SHORT',
            'order_type': 'LIMIT',
            'price': 2500.0,
            'size': 3.0,
            'status': 'active',
        }]
        adapter.normalize_stop_orders.return_value = [{
            'order_id': 'stop-1',
            'client_oid': 'stop-client-1',
            'symbol': 'BTCUSDT',
            'side': 'SHORT',
            'order_type': 'STOP_MARKET',
            'price': 0.0,
            'size': 12.0,
            'status': 'open',
            'is_active': True,
            'reduce_only': True,
            'close_order': False,
            'is_stop': True,
            'stop_direction': 'down',
            'stop_price': 67000.0,
            'stop_price_type': 'TP',
        }]
        adapter.normalize_recent_fills.return_value = [{
            'trade_id': 'fill-1',
            'order_id': 'order-1',
            'symbol': 'BTCUSDT',
            'side': 'LONG',
            'price': 68510.0,
            'size': 0.01,
            'value': 685.1,
            'fee': 0.5,
            'pnl': 1.5,
            'liquidity': 'taker',
            'filled_at_ms': 1714473600000,
        }]
        adapter.normalize_recent_closed_orders.return_value = [{
            'order_id': 'done-1',
            'client_oid': 'client-2',
            'symbol': 'BTCUSDT',
            'side': 'SHORT',
            'order_type': 'LIMIT',
            'price': 69000.0,
            'size': 0.01,
            'filled_size': 0.0,
            'status': 'done',
            'cancel_reason': 'IOC_CANCELLED',
            'closed_at_ms': 1714473600000,
        }]

        result = sync_live_exchange_state()

        self.assertTrue(result['ok'])
        adapter.get_account_overview.assert_called_once_with('USDT')
        adapter.get_positions.assert_called_once_with()
        adapter.get_open_orders.assert_called_once_with()
        adapter.get_stop_orders.assert_called_once_with()
        adapter.get_recent_fills.assert_called_once_with()
        adapter.get_recent_closed_orders.assert_called_once_with()
        state = AccountState.objects.get()
        self.assertEqual(state.balance, 123.0)
        position = Position.objects.get(source='exchange', status='OPEN')
        self.assertEqual(position.symbol, 'BTCUSDT')
        self.assertAlmostEqual(position.quantity, 0.012)
        order = ExchangeOpenOrder.objects.get(order_id='order-1')
        self.assertEqual(order.symbol, 'ETHUSDT')
        self.assertEqual(order.status, 'active')
        stop_order = ExchangeOpenOrder.objects.get(order_id='stop-1')
        self.assertEqual(stop_order.order_type, 'STOP_MARKET')
        fill = ExchangeFill.objects.get(trade_id='fill-1')
        self.assertEqual(fill.symbol, 'BTCUSDT')
        self.assertEqual(fill.order_id, 'order-1')
        closed_order = ExchangeClosedOrder.objects.get(order_id='done-1')
        self.assertEqual(closed_order.symbol, 'BTCUSDT')
        self.assertEqual(closed_order.status, 'done')


class LiveReconciliationTests(TestCase):
    def _intent(self, **overrides):
        values = {
            'client_oid': 'entry-1',
            'symbol': 'BTCUSDT',
            'side': 'LONG',
            'strategy': 'S1',
            'requested_quantity': 0.012,
            'submitted_quantity': 0.012,
            'stop_loss': 67000,
            'status': 'ACCEPTED',
        }
        values.update(overrides)
        return ExchangeExecutionIntent.objects.create(**values)

    def _adapter(self, mock_get_adapter, exchange_positions):
        adapter = mock_get_adapter.return_value
        ok = ExchangeOrderResult(True, {'code': '200000', 'data': {}})
        for method in ('get_account_overview', 'get_positions', 'get_open_orders',
                       'get_stop_orders', 'get_recent_fills', 'get_recent_closed_orders'):
            getattr(adapter, method).return_value = ok
        adapter.normalize_positions.return_value = exchange_positions
        adapter.normalize_open_orders.return_value = []
        adapter.normalize_stop_orders.return_value = []
        adapter.normalize_recent_fills.return_value = []
        adapter.normalize_recent_closed_orders.return_value = []

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_unknown_exchange_position_halts_instead_of_being_adopted(self, mock_get_adapter):
        from risk.trading_state import current
        self._adapter(mock_get_adapter, [{
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity_base': 0.012, 'entry_price': 68000.0,
            'mark_price': 68500.0, 'position_size_usd': 816.0, 'unrealized_pnl': 0.0, 'leverage': 5}])
        result = sync_live_exchange_state()

        self.assertTrue(result['payload']['reconciliation']['halted'])
        self.assertEqual(current().state, 'HALT')

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_exchange_visibility_failure_requires_manual_close_only(self, mock_get_adapter):
        from risk.trading_state import current

        self._adapter(mock_get_adapter, [])
        mock_get_adapter.return_value.get_positions.return_value = ExchangeOrderResult(
            False, {'error': 'timeout'},
        )

        result = sync_live_exchange_state()

        self.assertFalse(result['ok'])
        self.assertEqual(result['payload']['critical_read_failures'], ['positions'])
        state = current()
        self.assertEqual(state.state, 'CLOSE_ONLY')
        self.assertTrue(state.manual_unlock)

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_matching_position_without_exchange_stop_halts(self, mock_get_adapter):
        from risk.trading_state import current

        self._intent()
        self._adapter(mock_get_adapter, [{
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity_base': 0.012,
            'entry_price': 68000.0, 'mark_price': 68500.0,
            'position_size_usd': 816.0, 'unrealized_pnl': 0.0, 'leverage': 5,
        }])

        result = sync_live_exchange_state()

        issues = [m['issue'] for m in result['payload']['reconciliation']['mismatches']]
        self.assertIn('UNPROTECTED_ON_EXCHANGE', issues)
        self.assertEqual(current().state, 'HALT')

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_matching_books_do_not_halt(self, mock_get_adapter):
        from risk.trading_state import current
        intent = self._intent(signal_ref='consensus:42')
        self._adapter(mock_get_adapter, [{
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity_base': 0.012, 'entry_price': 68000.0,
            'mark_price': 68500.0, 'position_size_usd': 816.0, 'unrealized_pnl': 0.0, 'leverage': 5}])
        mock_get_adapter.return_value.normalize_stop_orders.return_value = [{
            'order_id': 'stop-1', 'symbol': 'BTCUSDT', 'side': 'SHORT',
            'status': 'open', 'is_active': True, 'reduce_only': True,
            'close_order': False, 'stop_direction': 'down', 'stop_price': 67000.0,
        }]
        result = sync_live_exchange_state()

        self.assertEqual(result['payload']['reconciliation']['mismatches'], [])
        self.assertEqual(current().state, 'NORMAL')
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'OPEN')
        mirror = Position.objects.get(source='exchange', status='OPEN')
        self.assertEqual(mirror.strategy, 'S1')
        self.assertEqual(mirror.consensus_signal_id, 42)
        self.assertEqual(mirror.analyst_snapshot['execution_intent'], 'entry-1')

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_uncertain_intent_halts_even_when_position_and_stop_match(self, mock_get_adapter):
        from risk.trading_state import current

        intent = self._intent(status='UNCERTAIN')
        self._adapter(mock_get_adapter, [{
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity_base': 0.012,
            'entry_price': 68000.0, 'mark_price': 68500.0,
            'position_size_usd': 816.0, 'unrealized_pnl': 0.0, 'leverage': 5,
        }])
        mock_get_adapter.return_value.normalize_stop_orders.return_value = [{
            'order_id': 'stop-1', 'symbol': 'BTCUSDT', 'side': 'SHORT',
            'status': 'open', 'is_active': True, 'reduce_only': True,
            'close_order': False, 'stop_direction': 'down', 'stop_price': 67000.0,
        }]

        result = sync_live_exchange_state()

        issues = [m['issue'] for m in result['payload']['reconciliation']['mismatches']]
        self.assertIn('UNRESOLVED_EXECUTION_INTENT', issues)
        self.assertEqual(current().state, 'HALT')
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'UNCERTAIN')

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_pending_entry_order_does_not_halt_before_fill(self, mock_get_adapter):
        from risk.trading_state import current

        intent = self._intent()
        self._adapter(mock_get_adapter, [])
        mock_get_adapter.return_value.normalize_open_orders.return_value = [{
            'order_id': 'order-1', 'client_oid': 'entry-1', 'symbol': 'BTCUSDT',
            'side': 'LONG', 'order_type': 'LIMIT', 'price': 68000,
            'size': 12, 'status': 'active',
        }]

        result = sync_live_exchange_state()

        self.assertEqual(result['payload']['reconciliation']['mismatches'], [])
        self.assertEqual(current().state, 'NORMAL')
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'ACCEPTED')

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_closing_intent_is_closed_when_position_disappears(self, mock_get_adapter):
        from risk.trading_state import current

        intent = self._intent(status='CLOSING')
        self._adapter(mock_get_adapter, [])

        result = sync_live_exchange_state()

        self.assertEqual(result['payload']['reconciliation']['mismatches'], [])
        self.assertEqual(current().state, 'NORMAL')
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'CLOSED')
