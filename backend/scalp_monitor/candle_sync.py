"""Keeps 1-minute candles fresh for the symbols S20 H1 trades, using
Binance's public futures REST klines endpoint directly — deliberately NOT
relying on the ingester app's own scheduled fetch tasks, whose Celery beat
schedule cannot be verified as actually running from here (the live DB was
found to have OpenInterest essentially empty and candles several days
stale). This mirrors carry_monitor's design: a self-contained data path
that does not depend on other infrastructure being healthy.

Writes into the same ingester.models.Candle table/schema so nothing else in
the codebase needs to change to benefit from a fresher 1m series.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests

KLINES_URL = 'https://fapi.binance.com/fapi/v1/klines'
TIMEOUT_SECONDS = 15
MAX_LIMIT = 1500


def _fetch_klines(symbol: str, start_ms: int, end_ms: int) -> list[list]:
    response = requests.get(KLINES_URL, params={
        'symbol': symbol, 'interval': '1m',
        'startTime': start_ms, 'endTime': end_ms, 'limit': MAX_LIMIT,
    }, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def sync_minute_candles(symbol: str, lookback_days: int = 40) -> int:
    """Fetch and store any 1m candles between the last stored one (or
    `lookback_days` ago if none) and the last fully closed minute. Returns
    the number of new rows written."""
    from ingester.models import Candle

    now = datetime.now(timezone.utc)
    last_closed_minute = now.replace(second=0, microsecond=0) - timedelta(minutes=1)

    latest = (Candle.objects.filter(symbol=symbol, interval='1m')
             .order_by('-timestamp').values_list('timestamp', flat=True).first())
    start = (latest + timedelta(minutes=1)) if latest else now - timedelta(days=lookback_days)
    if start > last_closed_minute:
        return 0

    written = 0
    cursor = start
    while cursor <= last_closed_minute:
        chunk_end = min(cursor + timedelta(minutes=MAX_LIMIT - 1), last_closed_minute)
        rows = _fetch_klines(symbol, int(cursor.timestamp() * 1000),
                             int(chunk_end.timestamp() * 1000))
        candles = []
        for row in rows:
            open_time = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            if open_time > last_closed_minute:
                continue
            candles.append(Candle(
                symbol=symbol, interval='1m', timestamp=open_time,
                open=Decimal(row[1]), high=Decimal(row[2]), low=Decimal(row[3]),
                close=Decimal(row[4]), volume=Decimal(row[5]),
                quote_volume=Decimal(row[7]), num_trades=int(row[8]),
                taker_buy_volume=Decimal(row[9]), taker_buy_quote_volume=Decimal(row[10]),
                is_closed=True,
            ))
        if candles:
            Candle.objects.bulk_create(candles, ignore_conflicts=True)
            written += len(candles)
        if not rows:
            break
        cursor = chunk_end + timedelta(minutes=1)
    return written
