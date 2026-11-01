"""
Binance Futures WebSocket client for real-time data streaming.
Connects to wss://fstream.binance.com for klines, funding rate, and liquidation data.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import websockets
from django.conf import settings
from django.db import transaction
from asgiref.sync import sync_to_async

from .models import (
    Candle, FundingRate, Liquidation, AggTrade, WhaleCVD, RetailCVD,
    WhaleThreshold, OrderBookSnapshot,
)
from .orderbook import summarize_depth

logger = logging.getLogger(__name__)

INTERVALS = ['1m', '5m', '15m', '1h', '4h']


class BinanceWebSocketClient:
    """Async WebSocket client for Binance Futures streams."""

    def __init__(self):
        self.base_url = settings.BINANCE_WS_URL
        self.running = False
        self._connections = []
        self._last_depth_persisted = {}
        self._aggtrade_buffer = []
        self._stop_event = None
        # Load pairs from WatchedPair at startup; falls back to settings
        try:
            from .models import WatchedPair
            active_symbols = WatchedPair.get_active_symbols() or settings.TRADING_PAIRS
            symbols = [
                *getattr(settings, 'GLOBAL_CONTEXT_PAIRS', ['BTCUSDT', 'ETHUSDT']),
                *active_symbols,
            ]
            self.trade_pairs = [s.lower() for s in dict.fromkeys(active_symbols)]
            self.pairs = [s.lower() for s in dict.fromkeys(symbols)]
            self._init_breadth_pairs()
        except Exception:
            self.trade_pairs = [p.lower() for p in dict.fromkeys(settings.TRADING_PAIRS)]
            symbols = [
                *getattr(settings, 'GLOBAL_CONTEXT_PAIRS', ['BTCUSDT', 'ETHUSDT']),
                *settings.TRADING_PAIRS,
            ]
            self.pairs = [p.lower() for p in dict.fromkeys(symbols)]
            self._init_breadth_pairs()

    def _init_breadth_pairs(self):
        """Breadth-only alts: closed context candles, nothing else."""
        existing = set(self.pairs)
        self.breadth_pairs = [
            s.lower() for s in dict.fromkeys(getattr(settings, 'BREADTH_PAIRS', []))
            if s.lower() not in existing
        ]
        self._breadth_symbols = {s.upper() for s in self.breadth_pairs}

    def _build_stream_urls(self):
        """Build routed URLs required by Binance's split market-data service.

        Since April 2026, depth belongs on ``/public`` while klines, trades,
        mark price and liquidations belong on ``/market``.  Mixing them on the
        legacy root can produce a healthy WebSocket that never emits events.
        """
        market_streams = []
        public_streams = []
        trade_pairs = set(getattr(self, 'trade_pairs', self.pairs))

        for pair in self.pairs:
            # Kline streams for each interval
            for interval in INTERVALS:
                market_streams.append(f"{pair}@kline_{interval}")

            # Mark price + funding rate (every 3s)
            market_streams.append(f"{pair}@markPrice")

            # High-rate microstructure feeds are required only for instruments
            # we may evaluate.  Global BTC/ETH context needs candles and mark
            # price, not thousands of extra writes per minute.
            if pair in trade_pairs:
                market_streams.append(f"{pair}@forceOrder")
                market_streams.append(f"{pair}@aggTrade")

                # Partial L2 snapshots. Binance publishes every 500ms;
                # persistence is downsampled separately to keep storage bounded.
                if getattr(settings, 'ORDER_BOOK_STREAM_ENABLED', True):
                    public_streams.append(f"{pair}@depth20@500ms")

        # Breadth-only alts: three context intervals, no mark price, trades
        # or depth.  Persisted on close only (see _handle_kline).
        for pair in getattr(self, 'breadth_pairs', []):
            for interval in getattr(settings, 'BREADTH_INTERVALS', ['15m', '1h', '4h']):
                market_streams.append(f"{pair}@kline_{interval}")

        base_url = self.base_url.rstrip('/')
        urls = {
            'market': f"{base_url}/market/stream?streams={'/'.join(market_streams)}",
        }
        if public_streams:
            urls['public'] = f"{base_url}/public/stream?streams={'/'.join(public_streams)}"
        return urls

    def _build_stream_url(self):
        """Backward-compatible market URL; use ``_build_stream_urls`` in code."""
        return self._build_stream_urls()['market']

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
            elif '@depth20' in stream:
                await self._handle_depth(payload)
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    @sync_to_async
    def _handle_kline(self, data):
        """Process kline/candlestick data."""
        kline = data.get('k', {})
        if not kline:
            return

        # Breadth-only symbols store closed bars only: ~4 upserts/s per stream
        # would otherwise dwarf the instruments we actually evaluate.
        if not kline.get('x') and kline.get('s') in getattr(self, '_breadth_symbols', ()):
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
        self._process_aggtrade_batch([data])

    def _process_aggtrade_batch(self, events):
        """Persist one receive-window in one SQLite transaction.

        Raw aggregate trades remain available for research while CVD is stored
        at the flush cadence instead of once per tick.  This preserves the
        directional sum and removes the write amplification that previously
        starved WebSocket keepalives.
        """
        if not events:
            return

        parsed = []
        symbols = set()
        for data in events:
            symbol = data['s']
            ts = datetime.fromtimestamp(data['T'] / 1000, tz=timezone.utc)
            price = Decimal(data['p'])
            quantity = Decimal(data['q'])
            is_buyer_maker = data['m']
            usd_value = (price * quantity).quantize(Decimal('0.01'))
            parsed.append((symbol, ts, price, quantity, usd_value, is_buyer_maker))
            symbols.add(symbol)

        with transaction.atomic():
            thresholds = {}
            whale_previous = {}
            retail_previous = {}
            for symbol in symbols:
                threshold_row = WhaleThreshold.objects.filter(
                    symbol=symbol,
                ).order_by('-timestamp').first()
                thresholds[symbol] = (
                    threshold_row.threshold_usd if threshold_row else Decimal('10000.00')
                )
                whale_row = WhaleCVD.objects.filter(symbol=symbol).order_by('-timestamp').first()
                retail_row = RetailCVD.objects.filter(symbol=symbol).order_by('-timestamp').first()
                whale_previous[symbol] = (
                    whale_row.cumulative_delta if whale_row else Decimal('0')
                )
                retail_previous[symbol] = (
                    retail_row.cumulative_delta if retail_row else Decimal('0')
                )

            AggTrade.objects.bulk_create([
                AggTrade(
                    symbol=symbol,
                    timestamp=ts,
                    price=price,
                    quantity=quantity,
                    usd_value=usd_value,
                    is_buyer_maker=is_buyer_maker,
                )
                for symbol, ts, price, quantity, usd_value, is_buyer_maker in parsed
            ], batch_size=1000)

            buckets = {}
            for symbol, ts, _price, _quantity, usd_value, is_buyer_maker in parsed:
                delta = usd_value if not is_buyer_maker else -usd_value
                bucket_name = 'whale' if usd_value >= thresholds[symbol] else 'retail'
                key = (symbol, bucket_name)
                bucket = buckets.setdefault(key, {'delta': Decimal('0'), 'timestamp': ts})
                bucket['delta'] += delta
                bucket['timestamp'] = max(bucket['timestamp'], ts)

            for (symbol, bucket_name), bucket in buckets.items():
                if bucket_name == 'whale':
                    WhaleCVD.objects.create(
                        symbol=symbol,
                        timestamp=bucket['timestamp'],
                        cumulative_delta=whale_previous[symbol] + bucket['delta'],
                    )
                else:
                    RetailCVD.objects.create(
                        symbol=symbol,
                        timestamp=bucket['timestamp'],
                        cumulative_delta=retail_previous[symbol] + bucket['delta'],
                    )

    async def _handle_aggtrade(self, data):
        buffer = getattr(self, '_aggtrade_buffer', None)
        if buffer is None:
            await sync_to_async(self._process_aggtrade, thread_sensitive=True)(data)
            return
        buffer.append(data)

    async def _flush_aggtrade_loop(self):
        """Flush high-rate trades without blocking the receive loop."""
        interval = max(
            0.1, float(getattr(settings, 'AGGTRADE_FLUSH_SECONDS', 1.0)),
        )
        while self.running or self._aggtrade_buffer:
            if self.running:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
            batch, self._aggtrade_buffer = self._aggtrade_buffer, []
            if not batch:
                continue
            try:
                await sync_to_async(
                    self._process_aggtrade_batch, thread_sensitive=True,
                )(batch)
            except Exception:
                self._aggtrade_buffer = batch + self._aggtrade_buffer
                logger.exception('AggTrade batch flush failed; batch retained for retry')
                if not self.running:
                    break

    def _process_depth(self, data):
        """Downsample and persist a normalized top-20 futures book snapshot."""
        symbol = data.get('s')
        event_ms = data.get('E') or data.get('T')
        if not symbol or event_ms is None:
            return None
        features = summarize_depth(data.get('b'), data.get('a'))
        if features is None:
            return None

        ts = datetime.fromtimestamp(int(event_ms) / 1000, tz=timezone.utc)
        last_by_symbol = getattr(self, '_last_depth_persisted', {})
        last_ts = last_by_symbol.get(symbol)
        interval = float(getattr(settings, 'ORDER_BOOK_SNAPSHOT_INTERVAL_SECONDS', 5.0))
        if last_ts is not None and (ts - last_ts).total_seconds() < interval:
            return None

        snapshot = OrderBookSnapshot.objects.create(
            symbol=symbol,
            timestamp=ts,
            last_update_id=int(data.get('u') or 0),
            **features,
        )
        last_by_symbol[symbol] = ts
        self._last_depth_persisted = last_by_symbol
        return snapshot

    @sync_to_async
    def _handle_depth(self, data):
        return self._process_depth(data)

    async def _consume_route(self, route, url):
        """Consume one routed connection with an independent reconnect loop."""
        reconnect_delay = 1
        STALE_TIMEOUT = 90   # seconds — force reconnect if no message received

        while self.running:
            try:
                logger.info(
                    "Connecting to Binance %s WebSocket (%s pairs)...",
                    route, len(self.pairs),
                )
                async with websockets.connect(
                    url,
                    ping_interval=20,      # Binance keepalive < 30s
                    ping_timeout=10,
                    close_timeout=10,
                    max_size=2**20,
                ) as ws:
                    logger.info(
                        "Connected to Binance %s route — streaming %s pairs",
                        route, len(self.pairs),
                    )
                    reconnect_delay = 1

                    while self.running:
                        try:
                            # Timeout = stale detection: if no msg in 90s → reconnect
                            message = await asyncio.wait_for(ws.recv(), timeout=STALE_TIMEOUT)
                            data = json.loads(message)
                            await self._process_message(data)
                        except asyncio.TimeoutError:
                            logger.warning(
                                "No %s data in %ss — forcing reconnect",
                                route, STALE_TIMEOUT,
                            )
                            break

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(
                    "%s WebSocket disconnected: %s. Reconnecting in %ss...",
                    route, e, reconnect_delay,
                )
            except Exception as e:
                logger.error("%s WebSocket error: %s", route, e, exc_info=True)

            if self.running:
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)   # max 30s backoff

    async def _poll_open_interest(self):
        """Keep required OI fresh even when this command runs without Celery."""
        from .binance_rest import BinanceRESTClient

        interval = max(60, int(getattr(settings, 'OPEN_INTEREST_POLL_SECONDS', 300)))
        while self.running:
            client = BinanceRESTClient()
            for symbol in getattr(self, 'trade_pairs', self.pairs):
                try:
                    await sync_to_async(
                        client.fetch_open_interest, thread_sensitive=True,
                    )(symbol.upper())
                except Exception as exc:
                    logger.error('OI poll error %s: %s', symbol, exc, exc_info=True)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    async def _run_shadow_pipeline(self):
        """Provide a self-contained local shadow loop when Celery is absent.

        Scheduled calls are idempotent, so running Celery Beat at the same time
        cannot create duplicate per-bar analyses or double-resolve a plan.
        """
        if not getattr(settings, 'AUCTION_SHADOW_ENABLED', True):
            return
        from l2_agents.tasks import (
            resolve_auction_shadow_plans,
            run_auction_shadow_cycle,
        )

        cycle_interval = max(
            60, int(getattr(settings, 'AUCTION_SHADOW_CYCLE_SECONDS', 300)),
        )
        resolve_interval = max(
            15, int(getattr(settings, 'AUCTION_SHADOW_RESOLVE_SECONDS', 60)),
        )
        next_cycle_at = 0.0
        while self.running:
            loop_time = asyncio.get_running_loop().time()
            try:
                await asyncio.to_thread(resolve_auction_shadow_plans.run)
                if loop_time >= next_cycle_at:
                    await asyncio.to_thread(run_auction_shadow_cycle.run)
                    next_cycle_at = loop_time + cycle_interval
            except Exception as exc:
                logger.error('Local auction shadow loop error: %s', exc, exc_info=True)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=resolve_interval,
                )
            except asyncio.TimeoutError:
                continue

    async def _run_setup_search_loop(self):
        """Local setup-search journal: 30 s after every closed 15m bar."""
        if not getattr(settings, 'SETUP_SEARCH_ENABLED', True):
            return
        from l1_filter.tasks import run_setup_search_cycle

        while self.running:
            now = time.time()
            wait = 900 - (now % 900) + 30
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait)
                return
            except asyncio.TimeoutError:
                pass
            try:
                result = await asyncio.to_thread(run_setup_search_cycle.run)
                logger.info('Setup search cycle: %s', result)
            except Exception as exc:
                logger.error('Setup search loop error: %s', exc, exc_info=True)

    async def _run_maintenance_loop(self):
        """Hourly whale threshold; daily pruning (02:30 UTC). Celery-free."""
        from .tasks import (
            prune_agg_trades,
            prune_order_book_snapshots,
            recalculate_whale_threshold,
        )

        last_prune_day = last_paper_day = None
        while self.running:
            try:
                await asyncio.to_thread(recalculate_whale_threshold.run)
                now = datetime.now(timezone.utc)
                # Only inside 02:00-03:00 UTC, never as a side effect of a restart.
                if now.hour == 2 and last_prune_day != now.date():
                    await asyncio.to_thread(prune_order_book_snapshots.run)
                    await asyncio.to_thread(prune_agg_trades.run)
                    last_prune_day = now.date()
                # Retry hourly after 03:00 UTC until yesterday's complete archive
                # is available. Unchanged windows return the saved ledger without
                # repeating the two-year replay.
                if (now.hour >= 3 and last_paper_day != now.date()
                        and getattr(settings, 'PAPER_FORWARD_ENABLED', True)):
                    report = await self._paper_forward_subprocess()
                    logger.info('Paper-forward: %s %s days', report['status'],
                                report.get('forward_days'))
                    yesterday = (now - timedelta(days=1)).date().isoformat()
                    if report.get('data_through', '') >= yesterday:
                        last_paper_day = now.date()
            except Exception as exc:
                logger.error('Maintenance loop error: %s', exc, exc_info=True)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=3600)
                return
            except asyncio.TimeoutError:
                continue

    async def _paper_forward_subprocess(self) -> dict:
        """Run the CPU-heavy multi-year replay in its own process.

        In a thread it holds the GIL long enough to starve the event loop,
        which made Binance drop both sockets (keepalive ping timeout) and lose
        candle-close events.
        """
        import sys
        from pathlib import Path

        manage = Path(settings.BASE_DIR) / 'manage.py'
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(manage), 'paper_forward', '--json',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            tail = stderr.decode(errors='replace').strip().splitlines()[-1:] or ['']
            raise RuntimeError(f'paper_forward exited {proc.returncode}: {tail[0]}')
        return json.loads(stdout.decode())

    async def _run_candle_repair_loop(self):
        """Every 5 minutes (+40 s), REST-repair candle closes lost on reconnect."""
        from .tasks import repair_missed_candle_closes

        while self.running:
            wait = 300 - (time.time() % 300) + 40
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await asyncio.to_thread(repair_missed_candle_closes)
            except Exception as exc:
                logger.error('Candle repair loop error: %s', exc, exc_info=True)

    async def connect(self):
        """Connect routed market/public streams and process them concurrently."""
        self.running = True
        self._stop_event = asyncio.Event()
        urls = self._build_stream_urls()
        consumers = [
            self._consume_route(route, url) for route, url in urls.items()
        ]
        consumers.append(self._poll_open_interest())
        consumers.append(self._run_shadow_pipeline())
        consumers.append(self._run_setup_search_loop())
        consumers.append(self._run_maintenance_loop())
        consumers.append(self._run_candle_repair_loop())
        consumers.append(self._flush_aggtrade_loop())
        await asyncio.gather(*consumers)

    def stop(self):
        """Stop the WebSocket client."""
        self.running = False
        if self._stop_event is not None:
            self._stop_event.set()
        logger.info("WebSocket client stopping...")
