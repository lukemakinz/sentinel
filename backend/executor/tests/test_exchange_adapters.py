from unittest.mock import Mock, patch

import requests
from django.test import TestCase, override_settings

from executor.exchange_adapters import (
    ExchangeOrderResult,
    KuCoinFuturesAdapter,
    get_exchange_adapter,
)
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

    def test_contract_sizing_never_rounds_up(self):
        adapter = KuCoinFuturesAdapter()
        self.assertEqual(adapter._contracts_from_quantity(0.0019, 0.001), 1)
        self.assertEqual(adapter._contracts_from_quantity(0.0009, 0.001), 0)

    @override_settings(KUCOIN_API_KEY='key', KUCOIN_API_SECRET='secret', KUCOIN_API_PASSPHRASE='pass')
    def test_sub_contract_order_is_rejected_without_api_call(self):
        from unittest.mock import patch

        WatchedPair.objects.create(symbol='BTCUSDT', active=True)
        adapter = KuCoinFuturesAdapter()
        with patch.object(adapter, '_request') as request:
            result = adapter.place_order({
                'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity': 0.0009,
                'entry_price': 100000, 'leverage': 3, 'order_type': 'MARKET',
            })

        self.assertFalse(result.ok)
        self.assertIn('below one KuCoin contract', result.payload['error'])
        request.assert_not_called()

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

    def test_normalize_stop_orders_exposes_protection_semantics(self):
        adapter = KuCoinFuturesAdapter()
        orders = adapter.normalize_stop_orders({
            'data': {'items': [{
                'id': 'stop-1',
                'symbol': 'XBTUSDTM',
                'side': 'sell',
                'type': 'market',
                'size': '2',
                'stop': 'down',
                'stopPrice': '67000',
                'stopPriceType': 'TP',
                'reduceOnly': True,
                'isActive': True,
                'status': 'open',
            }]}
        })
        self.assertEqual(orders[0]['symbol'], 'BTCUSDT')
        self.assertEqual(orders[0]['side'], 'SHORT')
        self.assertEqual(orders[0]['stop_direction'], 'down')
        self.assertEqual(orders[0]['stop_price'], 67000.0)
        self.assertTrue(orders[0]['reduce_only'])

    def test_normalize_recent_fills_maps_contract_symbol(self):
        adapter = KuCoinFuturesAdapter()
        fills = adapter.normalize_recent_fills({
            'data': [{
                'tradeId': 't-1',
                'orderId': 'o-1',
                'symbol': 'XBTUSDTM',
                'side': 'buy',
                'price': '68000',
                'size': '2',
                'value': '136000',
                'fee': '1.2',
                'realizedPnl': '5.5',
                'liquidity': 'taker',
                'tradeTime': '1714473600000',
            }]
        })
        self.assertEqual(fills[0]['symbol'], 'BTCUSDT')
        self.assertEqual(fills[0]['side'], 'LONG')
        self.assertEqual(fills[0]['trade_id'], 't-1')

    def test_normalize_recent_closed_orders_maps_contract_symbol(self):
        adapter = KuCoinFuturesAdapter()
        orders = adapter.normalize_recent_closed_orders({
            'data': [{
                'id': 'o-2',
                'clientOid': 'client-2',
                'symbol': 'ETHUSDTM',
                'side': 'sell',
                'type': 'limit',
                'price': '2500',
                'size': '3',
                'filledSize': '1',
                'status': 'done',
                'cancelReason': '',
                'updatedAt': '1714473600000',
            }]
        })
        self.assertEqual(orders[0]['symbol'], 'ETHUSDT')
        self.assertEqual(orders[0]['side'], 'SHORT')
        self.assertEqual(orders[0]['order_id'], 'o-2')

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


class ClientOrderIdTest(TestCase):
    def test_supplied_client_oid_is_sent_so_retries_are_idempotent(self):
        from unittest.mock import patch

        WatchedPair.objects.create(symbol='BTCUSDT', active=True)
        adapter = KuCoinFuturesAdapter()
        params = {'symbol': 'BTCUSDT', 'side': 'LONG', 'entry_price': 100000, 'quantity': 0.01,
                  'stop_loss': 99000, 'leverage': 3, 'order_type': 'MARKET',
                  'client_oid': 'sentinel-42'}
        with patch.object(adapter, '_request') as request:
            adapter.place_order(params)
            adapter.place_order(params)
        sent = [call.args[2]['clientOid'] for call in request.call_args_list]
        self.assertEqual(sent, ['sentinel-42', 'sentinel-42'])

    def test_live_entry_without_deterministic_client_oid_is_rejected(self):
        WatchedPair.objects.create(symbol='BTCUSDT', active=True)
        adapter = KuCoinFuturesAdapter()
        with patch.object(adapter, '_request') as request:
            result = adapter.place_protected_order({
                'symbol': 'BTCUSDT', 'side': 'LONG', 'entry_price': 100000,
                'quantity': 0.01, 'stop_loss': 99000, 'leverage': 3,
                'order_type': 'MARKET',
            })
        self.assertFalse(result.ok)
        self.assertIn('deterministic client_oid', result.payload['error'])
        request.assert_not_called()

    def test_ambiguous_submit_is_recovered_by_client_oid_without_retry(self):
        WatchedPair.objects.create(symbol='BTCUSDT', active=True)
        adapter = KuCoinFuturesAdapter()
        uncertain = ExchangeOrderResult(False, {
            'error': 'KuCoin request failed', 'submission_uncertain': True,
        })
        recovered = ExchangeOrderResult(True, {
            'code': '200000',
            'data': {'id': 'order-1', 'clientOid': 'sentinel-42'},
        })
        with patch.object(adapter, '_request', side_effect=[uncertain, recovered]) as request:
            result = adapter.place_protected_order({
                'symbol': 'BTCUSDT', 'side': 'LONG', 'entry_price': 100000,
                'quantity': 0.01, 'stop_loss': 99000, 'leverage': 3,
                'order_type': 'MARKET', 'client_oid': 'sentinel-42',
            })

        self.assertTrue(result.ok)
        self.assertTrue(result.payload['recovered_by_client_oid'])
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[0:2], ('POST', '/api/v1/st-orders'))
        self.assertEqual(
            request.call_args_list[1].args,
            ('GET', '/api/v1/orders/byClientOid?clientOid=sentinel-42'),
        )

    def test_unresolved_ambiguous_submit_requires_manual_reconciliation(self):
        WatchedPair.objects.create(symbol='BTCUSDT', active=True)
        adapter = KuCoinFuturesAdapter()
        uncertain = ExchangeOrderResult(False, {
            'error': 'KuCoin request failed', 'submission_uncertain': True,
        })
        missing = ExchangeOrderResult(False, {'code': '404000', 'msg': 'not found'})
        with patch.object(adapter, '_request', side_effect=[uncertain, missing]):
            result = adapter.place_protected_order({
                'symbol': 'BTCUSDT', 'side': 'LONG', 'entry_price': 100000,
                'quantity': 0.01, 'stop_loss': 99000, 'leverage': 3,
                'order_type': 'MARKET', 'client_oid': 'sentinel-42',
            })

        self.assertFalse(result.ok)
        self.assertTrue(result.payload['manual_reconciliation_required'])
        self.assertEqual(result.payload['client_oid'], 'sentinel-42')


class ProtectedExecutionTest(TestCase):
    def setUp(self):
        WatchedPair.objects.create(symbol='BTCUSDT', active=True)

    @override_settings(KUCOIN_STOP_PRICE_TYPE='TP')
    def test_long_entry_and_stop_are_submitted_atomically(self):
        adapter = KuCoinFuturesAdapter()
        with patch.object(adapter, '_request') as request:
            adapter.place_protected_order({
                'symbol': 'BTCUSDT', 'side': 'LONG', 'entry_price': 68000,
                'stop_loss': 67000, 'quantity': 0.0124, 'leverage': 3,
                'order_type': 'MARKET', 'client_oid': 'entry-1',
            })

        method, endpoint, payload = request.call_args.args
        self.assertEqual((method, endpoint), ('POST', '/api/v1/st-orders'))
        self.assertEqual(payload['side'], 'buy')
        self.assertEqual(payload['size'], 12)
        self.assertEqual(payload['triggerStopDownPrice'], '67000')
        self.assertNotIn('triggerStopUpPrice', payload)
        self.assertFalse(payload['reduceOnly'])
        self.assertEqual(payload['positionSide'], 'BOTH')

    @override_settings(KUCOIN_STOP_PRICE_TYPE='TP')
    def test_short_entry_uses_up_trigger(self):
        adapter = KuCoinFuturesAdapter()
        with patch.object(adapter, '_request') as request:
            adapter.place_protected_order({
                'symbol': 'BTCUSDT', 'side': 'SHORT', 'entry_price': 68000,
                'stop_loss': 69000, 'quantity': 0.012, 'leverage': 3,
                'order_type': 'LIMIT', 'client_oid': 'entry-2',
            })

        payload = request.call_args.args[2]
        self.assertEqual(payload['side'], 'sell')
        self.assertEqual(payload['triggerStopUpPrice'], '69000')
        self.assertEqual(payload['price'], '68000')
        self.assertEqual(payload['timeInForce'], 'GTC')

    def test_entry_without_valid_adverse_stop_fails_before_api(self):
        adapter = KuCoinFuturesAdapter()
        base = {
            'symbol': 'BTCUSDT', 'side': 'LONG', 'entry_price': 68000,
            'quantity': 0.012, 'leverage': 3, 'order_type': 'MARKET',
        }
        with patch.object(adapter, '_request') as request:
            missing = adapter.place_protected_order(base)
            wrong_side = adapter.place_protected_order({**base, 'stop_loss': 69000})

        self.assertFalse(missing.ok)
        self.assertFalse(wrong_side.ok)
        request.assert_not_called()

    def test_market_close_is_opposite_side_and_reduce_only(self):
        adapter = KuCoinFuturesAdapter()
        with patch.object(adapter, '_request') as request:
            adapter.close_position({
                'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity': 0.0124,
                'leverage': 3, 'client_oid': 'close-1',
            })

        method, endpoint, payload = request.call_args.args
        self.assertEqual((method, endpoint), ('POST', '/api/v1/orders'))
        self.assertEqual(payload['side'], 'sell')
        self.assertEqual(payload['type'], 'market')
        self.assertEqual(payload['size'], 12)
        self.assertTrue(payload['reduceOnly'])
        self.assertEqual(payload['clientOid'], 'close-1')

    def test_sub_contract_close_is_rejected(self):
        adapter = KuCoinFuturesAdapter()
        with patch.object(adapter, '_request') as request:
            result = adapter.close_position({
                'symbol': 'BTCUSDT', 'side': 'LONG', 'quantity': 0.0009,
            })
        self.assertFalse(result.ok)
        request.assert_not_called()


class KuCoinResponseSafetyTest(TestCase):
    @override_settings(
        KUCOIN_API_KEY='key', KUCOIN_API_SECRET='secret',
        KUCOIN_API_PASSPHRASE='pass',
    )
    def test_http_200_with_exchange_error_code_is_failure(self):
        adapter = KuCoinFuturesAdapter()
        response = Mock(ok=True, status_code=200, text='')
        response.json.return_value = {'code': '400100', 'msg': 'bad request'}
        adapter.session.request = Mock(return_value=response)

        result = adapter._request('GET', '/api/v1/orders?status=active')

        self.assertFalse(result.ok)
        self.assertEqual(result.payload['code'], '400100')
        self.assertNotIn('submission_uncertain', result.payload)

    @override_settings(
        KUCOIN_API_KEY='key', KUCOIN_API_SECRET='secret',
        KUCOIN_API_PASSPHRASE='pass',
    )
    def test_transport_error_is_structured_failure(self):
        adapter = KuCoinFuturesAdapter()
        adapter.session.request = Mock(side_effect=requests.Timeout('timeout'))

        result = adapter._request('GET', '/api/v1/orders?status=active')

        self.assertFalse(result.ok)
        self.assertEqual(result.payload['error_type'], 'Timeout')

    @override_settings(
        KUCOIN_API_KEY='key', KUCOIN_API_SECRET='secret',
        KUCOIN_API_PASSPHRASE='pass',
    )
    def test_post_transport_error_is_marked_uncertain(self):
        adapter = KuCoinFuturesAdapter()
        adapter.session.request = Mock(side_effect=requests.Timeout('timeout'))

        result = adapter._request('POST', '/api/v1/st-orders', {'clientOid': 'entry-1'})

        self.assertFalse(result.ok)
        self.assertTrue(result.payload['submission_uncertain'])

    @override_settings(
        KUCOIN_API_KEY='key', KUCOIN_API_SECRET='secret',
        KUCOIN_API_PASSPHRASE='pass',
    )
    def test_server_error_on_post_is_marked_uncertain(self):
        adapter = KuCoinFuturesAdapter()
        response = Mock(ok=False, status_code=503, text='unavailable')
        response.json.return_value = {'code': '503000', 'msg': 'unavailable'}
        adapter.session.request = Mock(return_value=response)

        result = adapter._request('POST', '/api/v1/orders', {'clientOid': 'close-1'})

        self.assertFalse(result.ok)
        self.assertTrue(result.payload['submission_uncertain'])
