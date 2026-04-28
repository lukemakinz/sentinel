from django.test import TestCase, override_settings

from executor.exchange_adapters import KuCoinFuturesAdapter, get_exchange_adapter
from ingester.models import WatchedPair


class ExchangeAdapterTest(TestCase):
    @override_settings(EXCHANGE_NAME='kucoin')
    def test_get_exchange_adapter_returns_kucoin(self):
        adapter = get_exchange_adapter()
        self.assertIsInstance(adapter, KuCoinFuturesAdapter)

    @override_settings(KUCOIN_API_KEY='', KUCOIN_API_SECRET='', KUCOIN_API_PASSPHRASE='')
    def test_kucoin_adapter_rejects_without_credentials(self):
        adapter = KuCoinFuturesAdapter()
        result = adapter.place_order({
            'symbol': 'XBTUSDTM',
            'side': 'LONG',
            'entry_price': 100000,
            'quantity': 1,
            'strategy': 'S4',
            'margin_mode': 'isolated',
            'leverage': 3,
            'order_type': 'MARKET',
        })
        self.assertFalse(result.ok)
        self.assertIn('error', result.payload)

    def test_supported_symbols_follow_watched_pairs(self):
        WatchedPair.objects.create(symbol='BTCUSDT', active=True)
        WatchedPair.objects.create(symbol='ETHUSDT', active=False)
        adapter = KuCoinFuturesAdapter()
        self.assertEqual(adapter.get_supported_symbols(), ['BTCUSDT'])

    def test_contracts_from_quantity_uses_contract_size(self):
        adapter = KuCoinFuturesAdapter()
        self.assertEqual(adapter._contracts_from_quantity(0.01, 0.001), 10)

    def test_normalize_positions_maps_contract_symbol(self):
        adapter = KuCoinFuturesAdapter()
        positions = adapter.normalize_positions({
            'data': [{
                'symbol': 'XBTUSDTM',
                'currentQty': '12',
                'avgEntryPrice': '68000',
                'markPrice': '68500',
                'unrealisedPnl': '6.5',
                'marginMode': 'ISOLATED',
            }]
        })
        self.assertEqual(positions[0]['symbol'], 'BTCUSDT')
        self.assertEqual(positions[0]['side'], 'LONG')
        self.assertEqual(positions[0]['quantity_base'], 0.012)

    def test_normalize_open_orders_maps_contract_symbol(self):
        adapter = KuCoinFuturesAdapter()
        orders = adapter.normalize_open_orders({
            'data': {
                'items': [{
                    'id': '1',
                    'clientOid': 'abc',
                    'symbol': 'ETHUSDTM',
                    'side': 'sell',
                    'type': 'limit',
                    'price': '2500',
                    'size': '3',
                    'status': 'active',
                }]
            }
        })
        self.assertEqual(orders[0]['symbol'], 'ETHUSDT')
        self.assertEqual(orders[0]['side'], 'SHORT')

    @override_settings(KUCOIN_API_KEY='', KUCOIN_API_SECRET='', KUCOIN_API_PASSPHRASE='')
    def test_kucoin_adapter_maps_symbol_before_submission(self):
        WatchedPair.objects.create(symbol='BTCUSDT', active=True)
        adapter = KuCoinFuturesAdapter()
        result = adapter.place_order({
            'symbol': 'BTCUSDT',
            'side': 'LONG',
            'entry_price': 100000,
            'quantity': 0.01,
            'strategy': 'S1C',
            'margin_mode': 'isolated',
            'leverage': 3,
            'order_type': 'MARKET',
        })
        self.assertFalse(result.ok)
        self.assertNotIn('Unsupported KuCoin futures symbol', result.payload.get('error', ''))
