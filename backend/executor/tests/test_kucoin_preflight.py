from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from executor.exchange_adapters import ExchangeOrderResult
from executor.models import ExchangeExecutionIntent


class KuCoinPreflightCommandTest(TestCase):
    @patch('executor.management.commands.kucoin_preflight.get_exchange_adapter')
    def test_missing_credentials_fail_without_network_calls(self, get_adapter):
        adapter = get_adapter.return_value
        adapter.credentials_configured.return_value = False

        with self.assertRaisesMessage(CommandError, 'credentials are not configured'):
            call_command('kucoin_preflight')

        adapter.get_positions.assert_not_called()

    @patch('executor.management.commands.kucoin_preflight.get_exchange_adapter')
    def test_empty_read_only_account_passes(self, get_adapter):
        adapter = get_adapter.return_value
        adapter.credentials_configured.return_value = True
        ok = ExchangeOrderResult(True, {'code': '200000', 'data': {}})
        adapter.get_account_overview.return_value = ok
        adapter.get_positions.return_value = ok
        adapter.get_open_orders.return_value = ok
        adapter.get_stop_orders.return_value = ok
        adapter.normalize_positions.return_value = []
        adapter.normalize_open_orders.return_value = []
        adapter.normalize_stop_orders.return_value = []
        output = StringIO()

        call_command('kucoin_preflight', stdout=output)

        self.assertIn('no order was submitted', output.getvalue())
        self.assertIn('active=0 unresolved=0', output.getvalue())
        adapter.get_account_overview.assert_called_once_with('USDT')
        adapter.get_stop_orders.assert_called_once_with()

    @patch('executor.management.commands.kucoin_preflight.get_exchange_adapter')
    def test_unprotected_position_fails(self, get_adapter):
        adapter = get_adapter.return_value
        adapter.credentials_configured.return_value = True
        ok = ExchangeOrderResult(True, {'code': '200000', 'data': {}})
        adapter.get_account_overview.return_value = ok
        adapter.get_positions.return_value = ok
        adapter.get_open_orders.return_value = ok
        adapter.get_stop_orders.return_value = ok
        adapter.normalize_positions.return_value = [{
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity_base': 0.01,
            'entry_price': 68000.0, 'mark_price': 68100.0,
        }]
        adapter.normalize_open_orders.return_value = []
        adapter.normalize_stop_orders.return_value = []

        with self.assertRaisesMessage(CommandError, 'UNPROTECTED_ON_EXCHANGE'):
            call_command('kucoin_preflight')

    @patch('executor.management.commands.kucoin_preflight.get_exchange_adapter')
    def test_unresolved_execution_intent_prevents_ready(self, get_adapter):
        adapter = get_adapter.return_value
        adapter.credentials_configured.return_value = True
        ok = ExchangeOrderResult(True, {'code': '200000', 'data': {}})
        adapter.get_account_overview.return_value = ok
        adapter.get_positions.return_value = ok
        adapter.get_open_orders.return_value = ok
        adapter.get_stop_orders.return_value = ok
        adapter.normalize_positions.return_value = []
        adapter.normalize_open_orders.return_value = []
        adapter.normalize_stop_orders.return_value = []
        ExchangeExecutionIntent.objects.create(
            client_oid='entry-uncertain', symbol='BTCUSDT', side='LONG',
            requested_quantity=0.012, submitted_quantity=0.012,
            stop_loss=67000, status='UNCERTAIN',
        )
        output = StringIO()

        with self.assertRaisesMessage(
            CommandError, 'entry-uncertain:UNCERTAIN',
        ):
            call_command('kucoin_preflight', stdout=output)

        self.assertIn('active=1 unresolved=1', output.getvalue())
        adapter.get_stop_orders.assert_called_once_with()

    @patch('executor.management.commands.kucoin_preflight.get_exchange_adapter')
    def test_protected_but_unknown_exchange_position_prevents_ready(self, get_adapter):
        adapter = get_adapter.return_value
        adapter.credentials_configured.return_value = True
        ok = ExchangeOrderResult(True, {'code': '200000', 'data': {}})
        adapter.get_account_overview.return_value = ok
        adapter.get_positions.return_value = ok
        adapter.get_open_orders.return_value = ok
        adapter.get_stop_orders.return_value = ok
        adapter.normalize_positions.return_value = [{
            'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity_base': 0.012,
            'entry_price': 68000.0, 'mark_price': 68100.0,
        }]
        adapter.normalize_open_orders.return_value = []
        adapter.normalize_stop_orders.return_value = [{
            'order_id': 'stop-1', 'symbol': 'BTCUSDT', 'side': 'SHORT',
            'status': 'open', 'is_active': True, 'reduce_only': True,
            'close_order': False, 'stop_direction': 'down',
            'stop_price': 67000.0,
        }]

        with self.assertRaisesMessage(CommandError, 'UNKNOWN_ON_EXCHANGE'):
            call_command('kucoin_preflight')

    @patch('executor.management.commands.kucoin_preflight.get_exchange_adapter')
    def test_pending_known_entry_order_can_pass_before_fill(self, get_adapter):
        adapter = get_adapter.return_value
        adapter.credentials_configured.return_value = True
        ok = ExchangeOrderResult(True, {'code': '200000', 'data': {}})
        adapter.get_account_overview.return_value = ok
        adapter.get_positions.return_value = ok
        adapter.get_open_orders.return_value = ok
        adapter.get_stop_orders.return_value = ok
        adapter.normalize_positions.return_value = []
        adapter.normalize_open_orders.return_value = [{
            'order_id': 'order-1', 'client_oid': 'entry-pending',
            'symbol': 'BTCUSDT', 'side': 'LONG', 'order_type': 'LIMIT',
            'price': 68000.0, 'size': 12, 'status': 'active',
        }]
        adapter.normalize_stop_orders.return_value = []
        ExchangeExecutionIntent.objects.create(
            client_oid='entry-pending', order_id='order-1', symbol='BTCUSDT',
            side='LONG', requested_quantity=0.012, submitted_quantity=0.012,
            stop_loss=67000, status='ACCEPTED',
        )
        output = StringIO()

        call_command('kucoin_preflight', stdout=output)

        self.assertIn('no order was submitted', output.getvalue())
        self.assertIn('active=1 unresolved=0', output.getvalue())
