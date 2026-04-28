"""Exchange adapter layer for live auto-execution."""
import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass

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

    def cancel_order(self, order_id: str) -> ExchangeOrderResult:
        raise NotImplementedError

    def get_open_orders(self, symbol: str | None = None) -> ExchangeOrderResult:
        raise NotImplementedError

    def get_positions(self) -> ExchangeOrderResult:
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

    def normalize_positions(self, payload: dict) -> list[dict]:
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
        response = self.session.request(
            method=method.upper(),
            url=f"{self.base_url}{endpoint}",
            data=body if body else None,
            headers=headers,
            timeout=10,
        )
        try:
            data = response.json()
        except Exception:
            data = {'status_code': response.status_code, 'text': response.text}
        return ExchangeOrderResult(response.ok, data)

    def place_order(self, trade_params: dict) -> ExchangeOrderResult:
        supported = self.get_supported_symbols()
        if supported is not None and trade_params['symbol'] not in supported:
            return ExchangeOrderResult(False, {'error': f"Symbol {trade_params['symbol']} is not enabled for live trading"})
        contract = self._resolve_contract(trade_params['symbol'])
        if not contract:
            return ExchangeOrderResult(False, {'error': f"Unsupported KuCoin futures symbol: {trade_params['symbol']}"})
        contracts = self._contracts_from_quantity(float(trade_params.get('quantity', 0.0)), contract['contract_size'])
        payload = {
            'clientOid': str(uuid.uuid4()),
            'symbol': contract['symbol'],
            'marginMode': str(trade_params.get('margin_mode', 'isolated')).upper(),
            'leverage': int(trade_params.get('leverage', settings.MAX_LEVERAGE)),
            'side': 'buy' if trade_params['side'] == 'LONG' else 'sell',
            'type': 'market' if trade_params.get('order_type') == 'MARKET' else 'limit',
            'size': contracts,
            'remark': f"sentinel_{trade_params.get('strategy', 'S1')}",
            'reduceOnly': False,
        }
        if payload['type'] == 'limit':
            payload['price'] = str(trade_params['entry_price'])
            payload['timeInForce'] = 'GTC'
        return self._request('POST', '/api/v1/orders', payload)

    def cancel_order(self, order_id: str) -> ExchangeOrderResult:
        return self._request('DELETE', f'/api/v1/orders/{order_id}')

    def get_open_orders(self, symbol: str | None = None) -> ExchangeOrderResult:
        endpoint = '/api/v1/orders'
        if symbol:
            endpoint += f'?symbol={symbol}&status=active'
        else:
            endpoint += '?status=active'
        return self._request('GET', endpoint)

    def get_positions(self) -> ExchangeOrderResult:
        return self._request('GET', '/api/v2/position')

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
        return max(int(round(quantity / contract_size)), 1)


def get_exchange_adapter() -> BaseExchangeAdapter:
    if settings.EXCHANGE_NAME == 'kucoin':
        return KuCoinFuturesAdapter()
    raise ValueError(f"Unsupported exchange: {settings.EXCHANGE_NAME}")
