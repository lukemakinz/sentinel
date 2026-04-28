from django.contrib.auth.models import User
from django.test import override_settings
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from ingester.models import WatchedPair
from unittest.mock import patch


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
