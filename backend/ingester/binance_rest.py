"""
Binance Futures REST client for periodic data fetches.
Handles: Open Interest, Long/Short Ratio, Top Trader Positions, 24h Tickers.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

import requests
from django.conf import settings

from .models import OpenInterest, LongShortRatio, TopTraderPosition, MarketTicker

logger = logging.getLogger(__name__)


class BinanceRESTClient:
    """REST client for Binance Futures public endpoints."""

    def __init__(self):
        self.base_url = settings.BINANCE_REST_URL
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
        })

    def _get(self, endpoint, params=None):
        """Make GET request with error handling."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"REST API error {endpoint}: {e}")
            return None

    def fetch_open_interest(self, symbol):
        """Fetch current open interest for a symbol."""
        data = self._get('/fapi/v1/openInterest', {'symbol': symbol})
        if not data:
            return None

        ts = datetime.fromtimestamp(data['time'] / 1000, tz=timezone.utc)
        oi = Decimal(data['openInterest'])

        obj, created = OpenInterest.objects.update_or_create(
            symbol=symbol,
            timestamp=ts,
            defaults={
                'open_interest': oi,
            }
        )
        logger.debug(f"OI {symbol}: {oi}")
        return obj

    def fetch_long_short_ratio(self, symbol, period='5m'):
        """Fetch global long/short account ratio."""
        data = self._get('/futures/data/globalLongShortAccountRatio', {
            'symbol': symbol,
            'period': period,
            'limit': 1,
        })
        if not data or len(data) == 0:
            return None

        entry = data[0]
        ts = datetime.fromtimestamp(entry['timestamp'] / 1000, tz=timezone.utc)

        obj, created = LongShortRatio.objects.update_or_create(
            symbol=symbol,
            timestamp=ts,
            defaults={
                'long_account': Decimal(entry['longAccount']),
                'short_account': Decimal(entry['shortAccount']),
                'long_short_ratio': Decimal(entry['longShortRatio']),
            }
        )
        logger.debug(f"L/S {symbol}: {entry['longShortRatio']}")
        return obj

    def fetch_top_trader_positions(self, symbol, period='5m'):
        """Fetch top trader long/short position ratio."""
        data = self._get('/futures/data/topLongShortPositionRatio', {
            'symbol': symbol,
            'period': period,
            'limit': 1,
        })
        if not data or len(data) == 0:
            return None

        entry = data[0]
        ts = datetime.fromtimestamp(entry['timestamp'] / 1000, tz=timezone.utc)

        obj, created = TopTraderPosition.objects.update_or_create(
            symbol=symbol,
            timestamp=ts,
            defaults={
                'long_account': Decimal(entry['longAccount']),
                'short_account': Decimal(entry['shortAccount']),
                'long_short_ratio': Decimal(entry['longShortRatio']),
            }
        )
        return obj

    def fetch_24h_ticker(self, symbol=None):
        """Fetch 24h price change statistics."""
        params = {}
        if symbol:
            params['symbol'] = symbol

        data = self._get('/fapi/v1/ticker/24hr', params)
        if not data:
            return []

        # Single symbol returns dict, all symbols returns list
        if isinstance(data, dict):
            data = [data]

        results = []
        ts = datetime.now(timezone.utc)

        for entry in data:
            sym = entry['symbol']
            # Only track our configured pairs
            if sym not in settings.TRADING_PAIRS:
                continue

            obj, _ = MarketTicker.objects.update_or_create(
                symbol=sym,
                timestamp=ts,
                defaults={
                    'price': Decimal(entry['lastPrice']),
                    'price_change_pct': Decimal(entry['priceChangePercent']),
                    'volume_24h': Decimal(entry['quoteVolume']),
                }
            )
            results.append(obj)

        return results

    def fetch_all_for_symbol(self, symbol):
        """Fetch all data types for a single symbol."""
        self.fetch_open_interest(symbol)
        self.fetch_long_short_ratio(symbol)
        self.fetch_top_trader_positions(symbol)
        self.fetch_24h_ticker(symbol)
        logger.info(f"Fetched all REST data for {symbol}")

    def fetch_all(self):
        """Fetch all data for all configured pairs."""
        for symbol in settings.TRADING_PAIRS:
            try:
                self.fetch_all_for_symbol(symbol)
            except Exception as e:
                logger.error(f"Error fetching data for {symbol}: {e}")

    def fetch_historical_candles(self, symbol, interval='1h', limit=500):
        """Fetch historical klines for backfilling."""
        data = self._get('/fapi/v1/klines', {
            'symbol': symbol,
            'interval': interval,
            'limit': limit,
        })
        if not data:
            return []

        from .models import Candle
        candles = []
        for k in data:
            ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            obj, _ = Candle.objects.update_or_create(
                symbol=symbol,
                interval=interval,
                timestamp=ts,
                defaults={
                    'open': Decimal(str(k[1])),
                    'high': Decimal(str(k[2])),
                    'low': Decimal(str(k[3])),
                    'close': Decimal(str(k[4])),
                    'volume': Decimal(str(k[5])),
                    'quote_volume': Decimal(str(k[7])),
                    'taker_buy_volume': Decimal(str(k[9])),
                    'taker_buy_quote_volume': Decimal(str(k[10])),
                    'num_trades': int(k[8]),
                    'is_closed': True,
                }
            )
            candles.append(obj)

        logger.info(f"Backfilled {len(candles)} candles for {symbol} {interval}")
        return candles
