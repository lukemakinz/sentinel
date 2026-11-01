"""Celery tasks for periodic data collection via REST API."""
import logging
from datetime import timedelta
from decimal import Decimal

import numpy as np
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _active_symbols():
    """Always use WatchedPair if configured, fall back to settings."""
    from .models import WatchedPair
    return WatchedPair.get_active_symbols()


def _market_data_symbols():
    """Trade watchlist plus mandatory cross-market context instruments."""
    context = getattr(settings, 'GLOBAL_CONTEXT_PAIRS', ['BTCUSDT', 'ETHUSDT'])
    return list(dict.fromkeys([*context, *_active_symbols()]))


@shared_task(name='ingester.fetch_open_interest')
def fetch_open_interest():
    """Fetch open interest for all watched pairs — runs every 5 min."""
    from .binance_rest import BinanceRESTClient
    client = BinanceRESTClient()
    for symbol in _market_data_symbols():
        try:
            client.fetch_open_interest(symbol)
        except Exception as e:
            logger.error(f"OI fetch error {symbol}: {e}")


@shared_task(name='ingester.fetch_long_short_ratio')
def fetch_long_short_ratio():
    """Fetch L/S ratio for all watched pairs — runs every 15 min."""
    from .binance_rest import BinanceRESTClient
    client = BinanceRESTClient()
    for symbol in _active_symbols():
        try:
            client.fetch_long_short_ratio(symbol)
        except Exception as e:
            logger.error(f"L/S ratio fetch error {symbol}: {e}")


@shared_task(name='ingester.fetch_top_trader_positions')
def fetch_top_trader_positions():
    """Fetch top trader positions for all watched pairs — runs every 15 min."""
    from .binance_rest import BinanceRESTClient
    client = BinanceRESTClient()
    for symbol in _active_symbols():
        try:
            client.fetch_top_trader_positions(symbol)
        except Exception as e:
            logger.error(f"Top trader fetch error {symbol}: {e}")


@shared_task(name='ingester.fetch_24h_tickers')
def fetch_24h_tickers():
    """Fetch 24h ticker data — runs every 5 min."""
    from .binance_rest import BinanceRESTClient
    client = BinanceRESTClient()
    try:
        client.fetch_24h_ticker()
    except Exception as e:
        logger.error(f"Ticker fetch error: {e}")


@shared_task(name='ingester.recalculate_whale_threshold')
def recalculate_whale_threshold():
    """Recalculate 95th-percentile whale threshold per symbol — runs every hour."""
    from .models import AggTrade, WhaleThreshold

    cutoff = timezone.now() - timedelta(hours=24)

    for symbol in _active_symbols():
        usd_values = list(
            AggTrade.objects
            .filter(symbol=symbol, timestamp__gte=cutoff)
            .values_list('usd_value', flat=True)
        )

        if len(usd_values) < 10:
            logger.info(f"Skipping whale threshold for {symbol}: only {len(usd_values)} trades in last 24h")
            continue

        threshold = float(np.percentile([float(v) for v in usd_values], 95))
        WhaleThreshold.objects.create(
            symbol=symbol,
            threshold_usd=Decimal(str(round(threshold, 2))),
        )
        logger.info(f"Whale threshold updated: {symbol} = ${threshold:.2f}")


@shared_task(name='ingester.check_data_freshness')
def check_data_freshness():
    """Watchdog: alert if no candle data in last 5 minutes."""
    from .models import Candle
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(minutes=5)
    stale_symbols = []

    for symbol in _active_symbols():
        last = Candle.objects.filter(symbol=symbol, interval='1m').order_by('-timestamp').first()
        if not last or last.timestamp < cutoff:
            age = int((timezone.now() - last.timestamp).total_seconds() / 60) if last else 9999
            stale_symbols.append({'symbol': symbol, 'age_minutes': age})
            logger.error(f"⚠️ STALE DATA: {symbol} last candle {age}m ago — ingester may have dropped")

    if stale_symbols:
        logger.error(f"Data freshness FAIL: {len(stale_symbols)} symbols stale: {stale_symbols}")
    else:
        logger.debug("Data freshness OK — all symbols live")

    return {'stale': stale_symbols}


@shared_task(name='ingester.prune_order_book_snapshots')
def prune_order_book_snapshots():
    """Archive complete days to Parquet, then keep the live L2 window bounded."""
    from .models import OrderBookSnapshot

    from .archive import archive_pending, safe_prune_cutoff

    retention_days = max(1, int(getattr(settings, 'ORDER_BOOK_RETENTION_DAYS', 14)))
    archive_pending('order_book')
    cutoff = safe_prune_cutoff('order_book', timezone.now() - timedelta(days=retention_days))
    deleted, _ = OrderBookSnapshot.objects.filter(timestamp__lt=cutoff).delete()
    logger.info(f"Pruned {deleted} order-book snapshots older than {retention_days} days")
    return {'deleted': deleted, 'retention_days': retention_days}


@shared_task(name='ingester.prune_agg_trades')
def prune_agg_trades():
    """Live aggTrades only feed 24h whale thresholds; archives hold history."""
    from .models import AggTrade

    from .archive import archive_pending, safe_prune_cutoff

    retention_days = max(2, int(getattr(settings, 'AGGTRADE_RETENTION_DAYS', 14)))
    archive_pending('agg_trades')
    cutoff = safe_prune_cutoff('agg_trades', timezone.now() - timedelta(days=retention_days))
    deleted, _ = AggTrade.objects.filter(timestamp__lt=cutoff).delete()
    logger.info(f"Pruned {deleted} aggTrades older than {retention_days} days")
    return {'deleted': deleted, 'retention_days': retention_days}


_INTERVAL_SECONDS = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400}


def repair_missed_candle_closes(grace_seconds: int = 90, lookback_hours: int = 48) -> dict:
    """Re-fetch bars whose close time passed but whose close event was lost.

    A WebSocket reconnect can drop the final kline update; the row then stays
    ``is_closed=False`` forever and every closed-only consumer (trend state,
    global context, replays) sees a silent hole.  REST is authoritative.
    """
    from .binance_rest import BinanceRESTClient
    from .models import Candle

    now = timezone.now()
    stale = {}
    rows = Candle.objects.filter(
        is_closed=False, timestamp__gte=now - timedelta(hours=lookback_hours),
        interval__in=list(_INTERVAL_SECONDS),
    ).values_list('symbol', 'interval', 'timestamp')
    for symbol, interval, ts in rows:
        close_at = ts + timedelta(seconds=_INTERVAL_SECONDS[interval] + grace_seconds)
        if close_at <= now:
            key = (symbol, interval)
            stale[key] = min(stale.get(key, ts), ts)
    if not stale:
        return {'repaired_series': 0}
    client = BinanceRESTClient()
    for (symbol, interval), oldest in stale.items():
        try:
            # Start at the oldest hole so gaps older than one page still heal;
            # each run advances up to 1500 bars.
            client.fetch_historical_candles(
                symbol, interval, 1500, start_ms=int(oldest.timestamp() * 1000),
            )
        except Exception as exc:  # one bad series must not stop the others
            logger.error('Candle repair failed %s %s: %s', symbol, interval, exc)
    logger.warning('Repaired missed candle closes: %s', sorted(stale))
    return {'repaired_series': len(stale)}


@shared_task(name='ingester.backfill_candles')
def backfill_candles():
    """Backfill evaluated instruments and warm the frozen breadth context."""
    from .binance_rest import BinanceRESTClient
    client = BinanceRESTClient()
    intervals = ['1m', '5m', '15m', '1h', '4h']
    market_symbols = _market_data_symbols()
    for symbol in market_symbols:
        for interval in intervals:
            try:
                limit = 500 if interval in ['1m', '5m'] else 200
                client.fetch_historical_candles(symbol, interval, limit)
            except Exception as e:
                logger.error(f"Backfill error {symbol} {interval}: {e}")
    # M3 must not spend its first two days treating an under-warmed SMA50 as
    # neutral breadth.  Context-only pairs receive enough closed bars for all
    # trend features, but still never receive trades, OI or depth.
    breadth_symbols = [
        symbol for symbol in getattr(settings, 'BREADTH_PAIRS', [])
        if symbol not in set(market_symbols)
    ]
    for symbol in breadth_symbols:
        for interval in getattr(settings, 'BREADTH_INTERVALS', ['15m', '1h', '4h']):
            try:
                limit = 220 if interval in {'1h', '4h'} else 100
                client.fetch_historical_candles(symbol, interval, limit)
            except Exception as e:
                logger.error(f"Breadth backfill error {symbol} {interval}: {e}")
    logger.info("Historical candle backfill complete")
