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


@shared_task(name='ingester.fetch_open_interest')
def fetch_open_interest():
    """Fetch open interest for all watched pairs — runs every 5 min."""
    from .binance_rest import BinanceRESTClient
    client = BinanceRESTClient()
    for symbol in _active_symbols():
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


@shared_task(name='ingester.backfill_candles')
def backfill_candles():
    """Backfill historical candles on startup — runs once."""
    from .binance_rest import BinanceRESTClient
    client = BinanceRESTClient()
    intervals = ['1m', '5m', '15m', '1h', '4h']
    for symbol in _active_symbols():
        for interval in intervals:
            try:
                limit = 500 if interval in ['1m', '5m'] else 200
                client.fetch_historical_candles(symbol, interval, limit)
            except Exception as e:
                logger.error(f"Backfill error {symbol} {interval}: {e}")
    logger.info("Historical candle backfill complete")
