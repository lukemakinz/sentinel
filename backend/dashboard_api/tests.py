from django.contrib.auth.models import User
from django.test import override_settings
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from django.utils import timezone
from ingester.models import WatchedPair
from unittest.mock import patch
from ingester.models import Candle
from executor.models import Position, ExchangeOpenOrder, Trade, ExchangeFill, ExchangeClosedOrder


class DashboardAuthTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='operator', password='secret123')

    def test_token_endpoint_returns_token_for_valid_credentials(self):
        response = self.client.post('/api/auth/token/', {'username': 'operator', 'password': 'secret123'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('token', response.data)

    def test_protected_endpoint_requires_authentication(self):
        response = self.client.get('/api/status/')
        self.assertIn(response.status_code, {401, 403})

    def test_authenticated_user_can_access_status(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        response = self.client.get('/api/status/')
        self.assertEqual(response.status_code, 200)

    def test_mtf_endpoint_exposes_non_executable_trend_state_contract(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

        response = self.client.get('/api/mtf/BTCUSDT/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['version'], 'trend-state-v1')
        self.assertTrue(response.data['learning_only'])
        self.assertFalse(response.data['execution_authorized'])
        self.assertEqual(
            set(response.data['timeframes']),
            {'5m', '15m', '1h', '4h', '1d'},
        )

    def test_auction_research_endpoint_is_read_only_and_exposes_learning(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

        response = self.client.get('/api/auction/research/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['shadow_only'])
        self.assertFalse(response.data['execution_authorized'])
        self.assertIn('m1_trend_filter', response.data['paired_comparison'])
        self.assertIn('learning_postmortems', response.data)

    def test_rotate_token_replaces_old_token(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        response = self.client.post('/api/auth/token/rotate/')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data['token'], token.key)

    @override_settings(
        EXCHANGE_NAME='kucoin',
        LIVE_TRADING_ENABLED=False,
        KUCOIN_API_KEY='',
        KUCOIN_API_SECRET='',
        KUCOIN_API_PASSPHRASE='',
        PROFIT_TO_SPOT_RATIO=0.10,
        KUCOIN_FUTURES_REST_URL='https://api-futures.kucoin.com',
        KUCOIN_FUTURES_WS_URL='wss://wsapi-futures.kucoin.com',
    )
    def test_exchange_integration_status_exposes_readiness(self):
        token = Token.objects.create(user=self.user)
        WatchedPair.objects.create(symbol='BTCUSDT', active=True)
        WatchedPair.objects.create(symbol='ETHUSDT', active=False)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

        response = self.client.get('/api/exchange/integration/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['exchange'], 'kucoin')
        self.assertFalse(response.data['live_trading_enabled'])
        self.assertFalse(response.data['credentials_configured'])
        self.assertEqual(response.data['active_symbols'], ['BTCUSDT'])

    @patch('dashboard_api.views.sync_live_exchange_state')
    def test_exchange_sync_endpoint_returns_task_payload(self, mock_sync_live_exchange_state):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        mock_sync_live_exchange_state.return_value = {'ok': True, 'payload': {'overview_ok': True}}

        response = self.client.post('/api/exchange/sync/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ok'])
        mock_sync_live_exchange_state.assert_called_once_with()

    @patch('dashboard_api.views.transfer_profit_reserve_to_spot')
    def test_exchange_transfer_profit_endpoint_accepts_optional_amount(self, mock_transfer_profit_reserve_to_spot):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        mock_transfer_profit_reserve_to_spot.return_value = {'ok': True, 'amount_usd': 12.5}

        response = self.client.post('/api/exchange/transfer-profit/', {'amount_usd': 12.5}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ok'])
        mock_transfer_profit_reserve_to_spot.assert_called_once_with(amount_usd=12.5)

    def test_exchange_transfer_profit_rejects_invalid_amount(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

        response = self.client.post('/api/exchange/transfer-profit/', {'amount_usd': 'abc'}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'invalid_amount_usd')

    def test_exchange_chart_snapshot_returns_candles_and_overlays(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        now = timezone.now()
        Candle.objects.create(
            symbol='BTCUSDT', interval='15m', timestamp=now,
            open=100000, high=100500, low=99900, close=100200,
            volume=12, quote_volume=1200000, taker_buy_volume=6,
            taker_buy_quote_volume=600000, num_trades=100, is_closed=True,
        )
        Position.objects.create(
            symbol='BTCUSDT', side='LONG', status='OPEN',
            entry_price=100100, current_price=100200, quantity=0.01, position_size_usd=1001,
            leverage=10, stop_loss=99500, liquidation_price=96000, margin_usd=100,
            remaining_quantity=0.01, source='exchange'
        )
        ExchangeOpenOrder.objects.create(
            order_id='k-1', symbol='BTCUSDT', side='SHORT', order_type='LIMIT',
            price=100800, size=0.01, status='active', source='exchange'
        )
        Trade.objects.create(
            symbol='BTCUSDT', strategy='S1C', side='LONG', entry_price=99950, exit_price=100400,
            quantity=0.01, position_size_usd=999.5, pnl=4.5, pnl_percent=0.45,
            risk_reward=1.5, entry_time=now, exit_time=now, close_reason='TP1'
        )
        ExchangeFill.objects.create(
            trade_id='f-1', order_id='k-1', symbol='BTCUSDT', side='LONG',
            price=100150, size=0.01, value=1001.5, fee=0.5, pnl=0.0,
            liquidity='taker', filled_at=now
        )
        ExchangeClosedOrder.objects.create(
            order_id='done-1', client_oid='client-9', symbol='BTCUSDT', side='SHORT',
            order_type='LIMIT', price=100800, size=0.01, filled_size=0.0,
            status='done', cancel_reason='IOC_CANCELLED', source='exchange', closed_at=now
        )

        response = self.client.get('/api/exchange/chart/?symbol=BTCUSDT&interval=15m&limit=100')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['symbol'], 'BTCUSDT')
        self.assertEqual(len(response.data['candles']), 1)
        self.assertEqual(len(response.data['positions']), 1)
        self.assertEqual(len(response.data['open_orders']), 1)
        self.assertEqual(len(response.data['trades']), 1)
        self.assertEqual(response.data['trades'][0]['strategy'], 'S1C')
        self.assertEqual(len(response.data['fills']), 1)
        self.assertEqual(len(response.data['closed_orders']), 1)

    def test_performance_returns_strategy_breakdown(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        now = timezone.now()
        Trade.objects.create(
            symbol='BTCUSDT', strategy='S1C', side='LONG', entry_price=100, exit_price=110,
            quantity=1, position_size_usd=100, pnl=10, pnl_percent=10,
            risk_reward=2.0, entry_time=now, exit_time=now, close_reason='TP1'
        )
        Trade.objects.create(
            symbol='ETHUSDT', strategy='S5', side='LONG', entry_price=200, exit_price=190,
            quantity=1, position_size_usd=200, pnl=-10, pnl_percent=-5,
            risk_reward=-1.0, entry_time=now, exit_time=now, close_reason='STOP_LOSS'
        )

        response = self.client.get('/api/performance/')

        self.assertEqual(response.status_code, 200)
        strategies = {item['strategy']: item for item in response.data['strategy_breakdown']}
        self.assertEqual(strategies['S1C']['total_pnl'], 10.0)
        self.assertEqual(strategies['S1C']['win_rate'], 100.0)
        self.assertEqual(strategies['S5']['total_pnl'], -10.0)
        self.assertEqual(strategies['S5']['losing_trades'], 1)

    def test_performance_can_filter_by_strategy(self):
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        now = timezone.now()
        Trade.objects.create(
            symbol='BTCUSDT', strategy='S1C', side='LONG', entry_price=100, exit_price=110,
            quantity=1, position_size_usd=100, pnl=10, pnl_percent=10,
            risk_reward=2.0, entry_time=now, exit_time=now, close_reason='TP1'
        )
        Trade.objects.create(
            symbol='ETHUSDT', strategy='S5', side='LONG', entry_price=200, exit_price=190,
            quantity=1, position_size_usd=200, pnl=-10, pnl_percent=-5,
            risk_reward=-1.0, entry_time=now, exit_time=now, close_reason='STOP_LOSS'
        )

        response = self.client.get('/api/performance/?strategy=S1C')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_trades'], 1)
        self.assertEqual(response.data['winning_trades'], 1)
        self.assertEqual(len(response.data['strategy_breakdown']), 1)
        self.assertEqual(response.data['strategy_breakdown'][0]['strategy'], 'S1C')
