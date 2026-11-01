"""Exchange adapter layer for live auto-execution."""
import base64
import hashlib
import hmac
import json
import math
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from django.conf import settings

KUCOIN_FUTURES_SYMBOL_MAP = {
    'BTCUSDT': {'symbol': 'XBTUSDTM', 'contract_size': 0.001},
    'ETHUSDT': {'symbol': 'ETHUSDTM', 'contract_size': 0.01},
    'SOLUSDT': {'symbol': 'SOLUSDTM', 'contract_size': 0.1},
    'BNBUSDT': {'symbol': 'BNBUSDTM', 'contract_size': 0.01},
}


@dataclass
class ExchangeOrderResult:
    ok: bool
    payload: dict


class BaseExchangeAdapter:
    name = 'base'

    def place_order(self, trade_params: dict) -> ExchangeOrderResult:
        raise NotImplementedError

    def place_protected_order(self, trade_params: dict) -> ExchangeOrderResult:
        raise NotImplementedError

    def prepare_protected_order(self, trade_params: dict) -> ExchangeOrderResult:
        raise NotImplementedError

    def submit_prepared_protected_order(self, prepared: dict) -> ExchangeOrderResult:
        raise NotImplementedError

    def close_position(self, position_params: dict) -> ExchangeOrderResult:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> ExchangeOrderResult:
        raise NotImplementedError

    def get_open_orders(self, symbol: str | None = None) -> ExchangeOrderResult:
        raise NotImplementedError

    def get_stop_orders(self, symbol: str | None = None) -> ExchangeOrderResult:
        raise NotImplementedError

    def get_order_by_client_oid(self, client_oid: str) -> ExchangeOrderResult:
        raise NotImplementedError

    def get_positions(self) -> ExchangeOrderResult:
        raise NotImplementedError

    def get_recent_fills(self, symbol: str | None = None) -> ExchangeOrderResult:
        raise NotImplementedError

    def get_recent_closed_orders(self, symbol: str | None = None) -> ExchangeOrderResult:
        raise NotImplementedError

    def transfer_profit_to_spot(self, amount_usd: float) -> ExchangeOrderResult:
        raise NotImplementedError

    def get_account_overview(self, currency: str = 'USDT') -> ExchangeOrderResult:
        raise NotImplementedError

    def get_supported_symbols(self) -> list[str] | None:
        return None

    def credentials_configured(self) -> bool:
        return False

    def normalize_open_orders(self, payload: dict) -> list[dict]:
        return payload.get('data', []) if isinstance(payload, dict) else []

    def normalize_stop_orders(self, payload: dict) -> list[dict]:
        return payload.get('data', []) if isinstance(payload, dict) else []

    def normalize_positions(self, payload: dict) -> list[dict]:
        return payload.get('data', []) if isinstance(payload, dict) else []

    def normalize_recent_fills(self, payload: dict) -> list[dict]:
        return payload.get('data', []) if isinstance(payload, dict) else []

    def normalize_recent_closed_orders(self, payload: dict) -> list[dict]:
        return payload.get('data', []) if isinstance(payload, dict) else []


class KuCoinFuturesAdapter(BaseExchangeAdapter):
    name = 'kucoin'

    def __init__(self):
        self.base_url = settings.KUCOIN_FUTURES_REST_URL.rstrip('/')
        self.api_key = settings.KUCOIN_API_KEY
        self.api_secret = settings.KUCOIN_API_SECRET
        self.passphrase = settings.KUCOIN_API_PASSPHRASE
        self.session = requests.Session()

    def _sign(self, ts_ms: str, method: str, endpoint: str, body: str = '') -> dict:
        prehash = f"{ts_ms}{method.upper()}{endpoint}{body}"
        signature = base64.b64encode(
            hmac.new(self.api_secret.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        passphrase = base64.b64encode(
            hmac.new(self.api_secret.encode(), self.passphrase.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            'KC-API-KEY': self.api_key,
            'KC-API-SIGN': signature,
            'KC-API-TIMESTAMP': ts_ms,
            'KC-API-PASSPHRASE': passphrase,
            'KC-API-KEY-VERSION': '2',
            'Content-Type': 'application/json',
        }

    def _request(self, method: str, endpoint: str, payload: dict | None = None) -> ExchangeOrderResult:
        if not self.credentials_configured():
            return ExchangeOrderResult(False, {'error': 'KuCoin credentials not configured'})

        body = json.dumps(payload) if payload else ''
        ts_ms = str(int(__import__('time').time() * 1000))
        headers = self._sign(ts_ms, method, endpoint, body)
        method = method.upper()
        mutating = method in {'POST', 'PUT', 'PATCH', 'DELETE'}
        try:
            response = self.session.request(
                method=method,
                url=f"{self.base_url}{endpoint}",
                data=body if body else None,
                headers=headers,
                timeout=10,
            )
        except requests.RequestException as exc:
            failure = {
                'error': 'KuCoin request failed',
                'error_type': type(exc).__name__,
            }
            if mutating:
                # A timeout/reset does not prove that the matching engine did
                # not accept the request. Never retry such a mutation blindly.
                failure['submission_uncertain'] = True
            return ExchangeOrderResult(False, failure)
        json_valid = True
        try:
            data = response.json()
        except Exception:
            json_valid = False
            data = {'status_code': response.status_code, 'text': response.text}
        # KuCoin commonly returns HTTP 200 with an application-level error code.
        # Treat only the documented success code as success; ambiguity must fail
        # closed in an execution adapter.
        api_ok = isinstance(data, dict) and str(data.get('code') or '') == '200000'
        ok = bool(response.ok and api_ok)
        if not ok and isinstance(data, dict) and 'error' not in data:
            data['error'] = 'KuCoin rejected or returned an ambiguous response'
        if (not ok and mutating
                and (int(response.status_code) >= 500 or (response.ok and not json_valid))):
            data['submission_uncertain'] = True
        return ExchangeOrderResult(ok, data)

    def _submit_with_client_oid_recovery(
        self, endpoint: str, payload: dict,
    ) -> ExchangeOrderResult:
        """Submit once; recover an ambiguous response without resubmitting."""
        result = self._request('POST', endpoint, payload)
        if result.ok or not result.payload.get('submission_uncertain'):
            return result

        client_oid = str(payload.get('clientOid') or '')
        lookup = self.get_order_by_client_oid(client_oid)
        found = lookup.payload.get('data') if lookup.ok and isinstance(lookup.payload, dict) else None
        if isinstance(found, dict) and str(found.get('clientOid') or '') == client_oid:
            return ExchangeOrderResult(True, {
                'code': '200000',
                'data': found,
                'recovered_by_client_oid': True,
                'original_submission_error': result.payload,
            })

        return ExchangeOrderResult(False, {
            **result.payload,
            'client_oid': client_oid,
            'recovery_lookup': lookup.payload,
            'manual_reconciliation_required': True,
        })

    def place_order(self, trade_params: dict) -> ExchangeOrderResult:
        """Compatibility entrypoint; every live entry must include a stop."""
        return self.place_protected_order(trade_params)

    def prepare_protected_order(self, trade_params: dict) -> ExchangeOrderResult:
        """Validate and build an entry request without touching the exchange.

        KuCoin's ``st-orders`` endpoint accepts the entry and attached trigger
        prices atomically.  Sentinel deliberately does not fall back to a plain
        entry when the stop is missing or invalid.
        """
        supported = self.get_supported_symbols()
        if supported is not None and trade_params['symbol'] not in supported:
            return ExchangeOrderResult(False, {'error': f"Symbol {trade_params['symbol']} is not enabled for live trading"})
        contract = self._resolve_contract(trade_params['symbol'])
        if not contract:
            return ExchangeOrderResult(False, {'error': f"Unsupported KuCoin futures symbol: {trade_params['symbol']}"})
        contracts = self._contracts_from_quantity(float(trade_params.get('quantity', 0.0)), contract['contract_size'])
        if contracts <= 0:
            return ExchangeOrderResult(False, {
                'error': 'Requested quantity is below one KuCoin contract; order rejected to preserve risk cap',
                'requested_quantity': float(trade_params.get('quantity', 0.0)),
                'contract_size': float(contract['contract_size']),
            })
        side = str(trade_params.get('side') or '').upper()
        if side not in {'LONG', 'SHORT'}:
            return ExchangeOrderResult(False, {'error': f'Invalid position side: {side}'})
        order_type = str(trade_params.get('order_type') or 'MARKET').upper()
        if order_type not in {'MARKET', 'LIMIT'}:
            return ExchangeOrderResult(False, {'error': f'Unsupported order type: {order_type}'})
        try:
            entry_price = float(trade_params.get('entry_price') or 0.0)
            stop_loss = float(trade_params.get('stop_loss') or 0.0)
        except (TypeError, ValueError):
            return ExchangeOrderResult(False, {'error': 'Entry and stop prices must be numeric'})
        if not math.isfinite(entry_price) or entry_price <= 0:
            return ExchangeOrderResult(False, {'error': 'A positive reference entry price is required'})
        if not math.isfinite(stop_loss) or stop_loss <= 0:
            return ExchangeOrderResult(False, {'error': 'A positive exchange-side stop_loss is required'})
        if side == 'LONG' and stop_loss >= entry_price:
            return ExchangeOrderResult(False, {'error': 'LONG stop_loss must be below entry_price'})
        if side == 'SHORT' and stop_loss <= entry_price:
            return ExchangeOrderResult(False, {'error': 'SHORT stop_loss must be above entry_price'})
        client_oid = str(trade_params.get('client_oid') or '').strip()
        if not client_oid:
            return ExchangeOrderResult(False, {
                'error': 'A deterministic client_oid is required for every live entry',
            })

        stop_price_type = str(getattr(settings, 'KUCOIN_STOP_PRICE_TYPE', 'TP')).upper()
        if stop_price_type not in {'TP', 'MP', 'IP'}:
            return ExchangeOrderResult(False, {
                'error': f'Unsupported KUCOIN_STOP_PRICE_TYPE: {stop_price_type}',
            })
        payload = {
            'clientOid': client_oid,
            'symbol': contract['symbol'],
            'marginMode': str(trade_params.get('margin_mode', 'isolated')).upper(),
            'leverage': int(trade_params.get('leverage', settings.MAX_LEVERAGE)),
            'positionSide': 'BOTH',
            'side': 'buy' if side == 'LONG' else 'sell',
            'type': order_type.lower(),
            'size': contracts,
            'remark': f"sentinel_{trade_params.get('strategy', 'S1')}",
            'reduceOnly': False,
            'stopPriceType': stop_price_type,
        }
        stop_key = 'triggerStopDownPrice' if side == 'LONG' else 'triggerStopUpPrice'
        payload[stop_key] = self._price_string(stop_loss)
        if payload['type'] == 'limit':
            payload['price'] = self._price_string(entry_price)
            payload['timeInForce'] = 'GTC'
        return ExchangeOrderResult(True, {
            'request': payload,
            'submission': {
                'client_oid': client_oid,
                'symbol': trade_params['symbol'],
                'contract_symbol': contract['symbol'],
                'side': side,
                'contracts': contracts,
                'quantity_base': contracts * float(contract['contract_size']),
                'stop_loss': stop_loss,
                'strategy': str(trade_params.get('strategy') or 'S1'),
            },
        })

    def submit_prepared_protected_order(self, prepared: dict) -> ExchangeOrderResult:
        """Submit an already persisted/validated entry exactly once."""
        payload = prepared.get('request') if isinstance(prepared, dict) else None
        if not isinstance(payload, dict) or not str(payload.get('clientOid') or '').strip():
            return ExchangeOrderResult(False, {'error': 'Invalid prepared protected order'})
        return self._submit_with_client_oid_recovery('/api/v1/st-orders', payload)

    def place_protected_order(self, trade_params: dict) -> ExchangeOrderResult:
        """Compatibility wrapper for validate + single protected submission."""
        prepared = self.prepare_protected_order(trade_params)
        if not prepared.ok:
            return prepared
        return self.submit_prepared_protected_order(prepared.payload)

    def close_position(self, position_params: dict) -> ExchangeOrderResult:
        """Submit a market close that can only reduce an existing position."""
        symbol = str(position_params.get('symbol') or '')
        contract = self._resolve_contract(symbol)
        if not contract:
            return ExchangeOrderResult(False, {'error': f'Unsupported KuCoin futures symbol: {symbol}'})
        side = str(position_params.get('side') or '').upper()
        if side not in {'LONG', 'SHORT'}:
            return ExchangeOrderResult(False, {'error': f'Invalid position side: {side}'})
        contracts = self._contracts_from_quantity(
            float(position_params.get('quantity') or 0.0),
            float(contract['contract_size']),
        )
        if contracts <= 0:
            return ExchangeOrderResult(False, {
                'error': 'Close quantity is below one KuCoin contract',
                'requested_quantity': float(position_params.get('quantity') or 0.0),
                'contract_size': float(contract['contract_size']),
            })
        client_oid = str(position_params.get('client_oid') or '').strip()
        if not client_oid:
            return ExchangeOrderResult(False, {
                'error': 'A deterministic client_oid is required for every live close',
            })
        payload = {
            'clientOid': client_oid,
            'symbol': contract['symbol'],
            'marginMode': str(position_params.get('margin_mode', 'isolated')).upper(),
            'leverage': int(position_params.get('leverage') or 1),
            'positionSide': 'BOTH',
            'side': 'sell' if side == 'LONG' else 'buy',
            'type': 'market',
            'size': contracts,
            'remark': 'sentinel_close',
            'reduceOnly': True,
        }
        return self._submit_with_client_oid_recovery('/api/v1/orders', payload)

    def cancel_order(self, order_id: str) -> ExchangeOrderResult:
        return self._request('DELETE', f'/api/v1/orders/{order_id}')

    def get_open_orders(self, symbol: str | None = None) -> ExchangeOrderResult:
        endpoint = '/api/v1/orders'
        if symbol:
            contract = self._resolve_contract(symbol)
            if not contract:
                return ExchangeOrderResult(False, {'error': f'Unsupported KuCoin futures symbol: {symbol}'})
            endpoint += f"?symbol={contract['symbol']}&status=active"
        else:
            endpoint += '?status=active'
        return self._request('GET', endpoint)

    def get_stop_orders(self, symbol: str | None = None) -> ExchangeOrderResult:
        endpoint = '/api/v1/stopOrders'
        if symbol:
            contract = self._resolve_contract(symbol)
            if not contract:
                return ExchangeOrderResult(False, {'error': f'Unsupported KuCoin futures symbol: {symbol}'})
            endpoint += f"?symbol={contract['symbol']}"
        return self._request('GET', endpoint)

    def get_order_by_client_oid(self, client_oid: str) -> ExchangeOrderResult:
        client_oid = str(client_oid or '').strip()
        if not client_oid:
            return ExchangeOrderResult(False, {'error': 'client_oid is required'})
        query = urlencode({'clientOid': client_oid})
        return self._request('GET', f'/api/v1/orders/byClientOid?{query}')

    def get_positions(self) -> ExchangeOrderResult:
        return self._request('GET', '/api/v2/position')

    def get_recent_fills(self, symbol: str | None = None) -> ExchangeOrderResult:
        endpoint = '/api/v1/recentFills'
        if symbol:
            contract = self._resolve_contract(symbol)
            if not contract:
                return ExchangeOrderResult(False, {'error': f"Unsupported KuCoin futures symbol: {symbol}"})
            endpoint += f"?symbol={contract['symbol']}"
        return self._request('GET', endpoint)

    def get_recent_closed_orders(self, symbol: str | None = None) -> ExchangeOrderResult:
        endpoint = '/api/v1/recentDoneOrders'
        if symbol:
            contract = self._resolve_contract(symbol)
            if not contract:
                return ExchangeOrderResult(False, {'error': f"Unsupported KuCoin futures symbol: {symbol}"})
            endpoint += f"?symbol={contract['symbol']}"
        return self._request('GET', endpoint)

    def get_account_overview(self, currency: str = 'USDT') -> ExchangeOrderResult:
        return self._request('GET', f'/api/v1/account-overview?currency={currency}')

    def transfer_profit_to_spot(self, amount_usd: float) -> ExchangeOrderResult:
        payload = {
            'currency': 'USDT',
            'amount': round(float(amount_usd), 8),
            'recAccountType': 'MAIN',
        }
        return self._request('POST', '/api/v3/transfer-out', payload)

    def get_supported_symbols(self) -> list[str] | None:
        try:
            from ingester.models import WatchedPair
            return WatchedPair.get_active_symbols()
        except Exception:
            return list(getattr(settings, 'TRADING_PAIRS', []))

    def credentials_configured(self) -> bool:
        return all((self.api_key, self.api_secret, self.passphrase))

    def normalize_open_orders(self, payload: dict) -> list[dict]:
        raw = payload.get('data', {}).get('items') if isinstance(payload, dict) else None
        orders = raw if isinstance(raw, list) else []
        normalized = []
        for order in orders:
            symbol = self._from_contract_symbol(order.get('symbol'))
            normalized.append({
                'order_id': order.get('id') or order.get('orderId'),
                'client_oid': order.get('clientOid'),
                'symbol': symbol or order.get('symbol'),
                'side': 'LONG' if order.get('side') == 'buy' else 'SHORT',
                'order_type': str(order.get('type', '')).upper(),
                'price': float(order.get('price') or 0.0),
                'size': float(order.get('size') or 0.0),
                'status': order.get('status') or order.get('state'),
                'reduce_only': bool(order.get('reduceOnly')),
                'close_order': bool(order.get('closeOrder')),
                'is_stop': False,
            })
        return normalized

    def normalize_stop_orders(self, payload: dict) -> list[dict]:
        raw = payload.get('data', {}).get('items') if isinstance(payload, dict) else None
        orders = raw if isinstance(raw, list) else []
        normalized = []
        for order in orders:
            symbol = self._from_contract_symbol(order.get('symbol'))
            stop_direction = str(order.get('stop') or '').lower()
            stop_price = order.get('stopPrice')
            if stop_price in (None, ''):
                if order.get('triggerStopDownPrice') not in (None, ''):
                    stop_direction = 'down'
                    stop_price = order.get('triggerStopDownPrice')
                elif order.get('triggerStopUpPrice') not in (None, ''):
                    stop_direction = 'up'
                    stop_price = order.get('triggerStopUpPrice')
            normalized.append({
                'order_id': order.get('id') or order.get('orderId'),
                'client_oid': order.get('clientOid'),
                'symbol': symbol or order.get('symbol'),
                'side': 'LONG' if str(order.get('side', '')).lower() == 'buy' else 'SHORT',
                'order_type': 'STOP_' + str(order.get('type') or 'market').upper(),
                'price': float(order.get('price') or 0.0),
                'size': float(order.get('size') or 0.0),
                'status': order.get('status') or order.get('state') or 'active',
                'is_active': bool(order.get('isActive', True)),
                'reduce_only': bool(order.get('reduceOnly')),
                'close_order': bool(order.get('closeOrder')),
                'is_stop': True,
                'stop_direction': stop_direction,
                'stop_price': float(stop_price or 0.0),
                'stop_price_type': str(order.get('stopPriceType') or ''),
            })
        return normalized

    def normalize_positions(self, payload: dict) -> list[dict]:
        raw = payload.get('data') if isinstance(payload, dict) else None
        positions = raw if isinstance(raw, list) else []
        normalized = []
        for pos in positions:
            symbol = self._from_contract_symbol(pos.get('symbol'))
            contract = self._resolve_contract(symbol) if symbol else None
            qty = float(pos.get('currentQty') or pos.get('currentQuantity') or pos.get('size') or 0.0)
            quantity_contracts = abs(qty)
            quantity_base = quantity_contracts * float(contract['contract_size']) if contract else quantity_contracts
            entry_price = float(pos.get('avgEntryPrice') or pos.get('avgEntryCost') or pos.get('entryPrice') or 0.0)
            mark_price = float(pos.get('markPrice') or 0.0)
            normalized.append({
                'symbol': symbol or pos.get('symbol'),
                'side': 'LONG' if qty >= 0 else 'SHORT',
                'quantity_contracts': quantity_contracts,
                'quantity_base': quantity_base,
                'entry_price': entry_price,
                'mark_price': mark_price,
                'position_size_usd': quantity_base * entry_price if entry_price > 0 else quantity_base * mark_price,
                'unrealized_pnl': float(pos.get('unrealisedPnl') or pos.get('unrealizedPnl') or 0.0),
                'margin_mode': str(pos.get('marginMode') or '').lower(),
                'leverage': int(float(pos.get('realLeverage') or pos.get('leverage') or 1)),
            })
        return normalized

    def normalize_recent_fills(self, payload: dict) -> list[dict]:
        raw = payload.get('data') if isinstance(payload, dict) else None
        fills = raw if isinstance(raw, list) else []
        normalized = []
        for fill in fills:
            symbol = self._from_contract_symbol(fill.get('symbol'))
            side = 'LONG' if str(fill.get('side', '')).lower() == 'buy' else 'SHORT'
            size = float(fill.get('size') or fill.get('qty') or 0.0)
            price = float(fill.get('price') or 0.0)
            value = float(fill.get('value') or (size * price))
            trade_time_raw = fill.get('tradeTime') or fill.get('createdAt') or fill.get('ts')
            try:
                trade_time_ms = int(float(trade_time_raw))
            except (TypeError, ValueError):
                trade_time_ms = 0
            normalized.append({
                'trade_id': str(fill.get('tradeId') or fill.get('id') or ''),
                'order_id': str(fill.get('orderId') or ''),
                'symbol': symbol or fill.get('symbol'),
                'side': side,
                'price': price,
                'size': size,
                'value': value,
                'fee': float(fill.get('fee') or fill.get('fixFee') or 0.0),
                'pnl': float(fill.get('realizedPnl') or fill.get('pnl') or 0.0),
                'liquidity': str(fill.get('liquidity') or fill.get('role') or ''),
                'filled_at_ms': trade_time_ms,
            })
        return [item for item in normalized if item['trade_id']]

    def normalize_recent_closed_orders(self, payload: dict) -> list[dict]:
        raw = payload.get('data') if isinstance(payload, dict) else None
        orders = raw if isinstance(raw, list) else []
        normalized = []
        for order in orders:
            symbol = self._from_contract_symbol(order.get('symbol'))
            side = 'LONG' if str(order.get('side', '')).lower() == 'buy' else 'SHORT'
            closed_at_raw = order.get('updatedAt') or order.get('createdAt') or order.get('orderTime') or order.get('ts')
            try:
                closed_at_ms = int(float(closed_at_raw))
            except (TypeError, ValueError):
                closed_at_ms = 0
            normalized.append({
                'order_id': str(order.get('id') or order.get('orderId') or ''),
                'client_oid': str(order.get('clientOid') or ''),
                'symbol': symbol or order.get('symbol'),
                'side': side,
                'order_type': str(order.get('type') or '').upper(),
                'price': float(order.get('price') or 0.0),
                'size': float(order.get('size') or 0.0),
                'filled_size': float(order.get('filledSize') or order.get('dealSize') or 0.0),
                'status': str(order.get('status') or order.get('state') or 'done'),
                'cancel_reason': str(order.get('cancelReason') or ''),
                'closed_at_ms': closed_at_ms,
            })
        return [item for item in normalized if item['order_id']]

    @staticmethod
    def _resolve_contract(symbol: str) -> dict | None:
        return KUCOIN_FUTURES_SYMBOL_MAP.get(symbol)

    @staticmethod
    def _from_contract_symbol(contract_symbol: str | None) -> str | None:
        if not contract_symbol:
            return None
        for local_symbol, meta in KUCOIN_FUTURES_SYMBOL_MAP.items():
            if meta['symbol'] == contract_symbol:
                return local_symbol
        return contract_symbol

    @staticmethod
    def _contracts_from_quantity(quantity: float, contract_size: float) -> int:
        if quantity <= 0 or contract_size <= 0:
            return 0
        # Never round a requested position up.  If it is smaller than one
        # contract, ``place_order`` rejects it instead of silently adding risk.
        return max(math.floor(quantity / contract_size + 1e-12), 0)

    @staticmethod
    def _price_string(price: float) -> str:
        return format(float(price), '.15g')


def get_exchange_adapter() -> BaseExchangeAdapter:
    if settings.EXCHANGE_NAME == 'kucoin':
        return KuCoinFuturesAdapter()
    raise ValueError(f"Unsupported exchange: {settings.EXCHANGE_NAME}")
