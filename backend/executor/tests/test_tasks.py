from unittest.mock import patch

from django.test import TestCase, override_settings

from executor.exchange_adapters import ExchangeOrderResult
from executor.models import AccountState, Position, ExchangeOpenOrder
from executor.tasks import transfer_profit_reserve_to_spot, sync_live_exchange_state


class ExecutorTaskTest(TestCase):
    @override_settings(LIVE_TRADING_ENABLED=True, PROFIT_TO_SPOT_RATIO=0.10)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_transfer_profit_reserve_uses_ratio_when_amount_missing(self, mock_get_adapter):
        adapter = mock_get_adapter.return_value
        adapter.transfer_profit_to_spot.return_value = ExchangeOrderResult(False, {'error': 'not implemented'})
        AccountState.objects.create(balance=150.0, equity=150.0, peak_equity=150.0)

        result = transfer_profit_reserve_to_spot()

        self.assertEqual(result['amount_usd'], 15.0)
        adapter.transfer_profit_to_spot.assert_called_once_with(15.0)

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.exchange_adapters.get_exchange_adapter')
    def test_sync_live_exchange_state_reads_overview_and_positions(self, mock_get_adapter):
        adapter = mock_get_adapter.return_value
        adapter.get_account_overview.return_value = ExchangeOrderResult(True, {'code': '200000', 'data': {'availableBalance': 123}})
        adapter.get_positions.return_value = ExchangeOrderResult(True, {'code': '200000', 'data': [{'symbol': 'XBTUSDTM'}]})
        adapter.get_open_orders.return_value = ExchangeOrderResult(True, {'code': '200000', 'data': {'items': []}})
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

        result = sync_live_exchange_state()

        self.assertTrue(result['ok'])
        adapter.get_account_overview.assert_called_once_with('USDT')
        adapter.get_positions.assert_called_once_with()
        adapter.get_open_orders.assert_called_once_with()
        state = AccountState.objects.get()
        self.assertEqual(state.balance, 123.0)
        position = Position.objects.get(source='exchange', status='OPEN')
        self.assertEqual(position.symbol, 'BTCUSDT')
        self.assertAlmostEqual(position.quantity, 0.012)
        order = ExchangeOpenOrder.objects.get(order_id='order-1')
        self.assertEqual(order.symbol, 'ETHUSDT')
        self.assertEqual(order.status, 'active')
