"""
Binance Futures WebSocket client for real-time data streaming.
Connects to wss://fstream.binance.com for klines, funding rate, and liquidation data.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import websockets
from django.conf import settings
from asgiref.sync import sync_to_async

from .models import Candle, FundingRate, Liquidation, AggTrade, WhaleCVD, RetailCVD, WhaleThreshold

logger = logging.getLogger(__name__)

INTERVALS = ['1m', '5m', '15m', '1h', '4h']


class BinanceWebSocketClient:
    """Async WebSocket client for Binance Futures streams."""

    def __init__(self):
        self.base_url = settings.BINANCE_WS_URL
        self.running = False
        self._connections = []
        # Load pairs from WatchedPair at startup; falls back to settings
        try:
            from .models import WatchedPair
            self.pairs = [s.lower() for s in WatchedPair.get_active_symbols()]
        except Exception:
            self.pairs = [p.lower() for p in settings.TRADING_PAIRS]

    def _build_stream_url(self):
        """Build combined stream URL for all pairs and data types."""
        streams = []

        for pair in self.pairs:
            # Kline streams for each interval
            for interval in INTERVALS:
                streams.append(f"{pair}@kline_{interval}")

            # Mark price + funding rate (every 3s)
            streams.append(f"{pair}@markPrice")

            # Liquidation orders
            streams.append(f"{pair}@forceOrder")

            # Aggregate trades (every tick — basis for Whale/Retail CVD)
            streams.append(f"{pair}@aggTrade")

        stream_path = '/'.join(streams)
        return f"{self.base_url}/stream?streams={stream_path}"

    async def _process_message(self, data):
        """Route incoming message to appropriate handler."""
        try:
            stream = data.get('stream', '')
            payload = data.get('data', {})

            if '@kline_' in stream:
                await self._handle_kline(payload)
            elif '@markPrice' in stream:
                await self._handle_mark_price(payload)
            elif '@forceOrder' in stream:
                await self._handle_liquidation(payload)
            elif '@aggTrade' in stream:
                await self._handle_aggtrade(payload)
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    @sync_to_async
    def _handle_kline(self, data):
        """Process kline/candlestick data."""
        kline = data.get('k', {})
        if not kline:
            return

        ts = datetime.fromtimestamp(kline['t'] / 1000, tz=timezone.utc)

        Candle.objects.update_or_create(
            symbol=kline['s'],
            interval=kline['i'],
            timestamp=ts,
            defaults={
                'open': Decimal(kline['o']),
                'high': Decimal(kline['h']),
                'low': Decimal(kline['l']),
                'close': Decimal(kline['c']),
                'volume': Decimal(kline['v']),
                'quote_volume': Decimal(kline['q']),
                'taker_buy_volume': Decimal(kline['V']),
                'taker_buy_quote_volume': Decimal(kline['Q']),
                'num_trades': int(kline['n']),
                'is_closed': kline['x'],
            }
        )

        if kline['x']:
            logger.debug(f"Closed candle: {kline['s']} {kline['i']} C={kline['c']}")

    @sync_to_async
    def _handle_mark_price(self, data):
        """Process mark price + funding rate."""
        ts = datetime.fromtimestamp(data['E'] / 1000, tz=timezone.utc)
        funding_rate = Decimal(data.get('r', '0'))

        # Only save when funding rate is non-zero (updated every 8h)
        if funding_rate != 0:
            FundingRate.objects.update_or_create(
                symbol=data['s'],
                timestamp=ts,
                defaults={
                    'funding_rate': funding_rate,
                    'mark_price': Decimal(data['p']),
                }
            )

    @sync_to_async
    def _handle_liquidation(self, data):
        """Process liquidation order."""
        order = data.get('o', {})
        if not order:
            return

        ts = datetime.fromtimestamp(order['T'] / 1000, tz=timezone.utc)
        price = Decimal(order['p'])
        qty = Decimal(order['q'])

        Liquidation.objects.create(
            symbol=order['s'],
            timestamp=ts,
            side=order['S'],
            price=price,
            quantity=qty,
            usd_value=price * qty,
        )
        logger.info(f"Liquidation: {order['s']} {order['S']} {qty} @ {price}")

    def _process_aggtrade(self, data):
        """Process aggTrade tick and update AggTrade + Whale/Retail CVD."""
        symbol = data['s']
        ts = datetime.fromtimestamp(data['T'] / 1000, tz=timezone.utc)
        price = Decimal(data['p'])
        quantity = Decimal(data['q'])
        is_buyer_maker = data['m']
        usd_value = (price * quantity).quantize(Decimal('0.01'))

        AggTrade.objects.create(
            symbol=symbol,
            timestamp=ts,
            price=price,
            quantity=quantity,
            usd_value=usd_value,
            is_buyer_maker=is_buyer_maker,
        )

        # Positive delta = buy pressure, negative = sell pressure
        delta = usd_value if not is_buyer_maker else -usd_value

        try:
            threshold = WhaleThreshold.objects.filter(symbol=symbol).latest('timestamp').threshold_usd
        except WhaleThreshold.DoesNotExist:
            threshold = Decimal('10000.00')

        if usd_value >= threshold:
            try:
                prev = WhaleCVD.objects.filter(symbol=symbol).latest('timestamp').cumulative_delta
            except WhaleCVD.DoesNotExist:
                prev = Decimal('0')
            WhaleCVD.objects.create(symbol=symbol, timestamp=ts, cumulative_delta=prev + delta)
        else:
            try:
                prev = RetailCVD.objects.filter(symbol=symbol).latest('timestamp').cumulative_delta
            except RetailCVD.DoesNotExist:
                prev = Decimal('0')
            RetailCVD.objects.create(symbol=symbol, timestamp=ts, cumulative_delta=prev + delta)

    @sync_to_async
    def _handle_aggtrade(self, data):
        self._process_aggtrade(data)

    async def connect(self):
        """Connect to Binance WebSocket and start processing."""
        self.running = True
        reconnect_delay = 1
        STALE_TIMEOUT = 90   # seconds — force reconnect if no message received

        while self.running:
            # Rebuild URL each reconnect so new WatchedPairs are picked up
            url = self._build_stream_url()
            last_msg = asyncio.get_event_loop().time()

            try:
                logger.info(f"Connecting to Binance WebSocket ({len(self.pairs)} pairs)...")
                async with websockets.connect(
                    url,
                    ping_interval=20,      # Binance keepalive < 30s
                    ping_timeout=10,
                    close_timeout=10,
                    max_size=2**20,
                ) as ws:
                    logger.info(f"Connected — streaming {len(self.pairs)} pairs")
                    reconnect_delay = 1

                    while self.running:
                        try:
                            # Timeout = stale detection: if no msg in 90s → reconnect
                            message = await asyncio.wait_for(ws.recv(), timeout=STALE_TIMEOUT)
                            last_msg = asyncio.get_event_loop().time()
                            data = json.loads(message)
                            await self._process_message(data)
                        except asyncio.TimeoutError:
                            logger.warning(f"No data in {STALE_TIMEOUT}s — forcing reconnect")
                            break

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket disconnected: {e}. Reconnecting in {reconnect_delay}s...")
            except Exception as e:
                logger.error(f"WebSocket error: {e}", exc_info=True)

            if self.running:
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)   # max 30s backoff

    def stop(self):
        """Stop the WebSocket client."""
        self.running = False
        logger.info("WebSocket client stopping...")
