"""
Download historical klines from Binance Futures REST API.

Usage:
    python manage.py download_history                         # 1 year, all watched pairs, 1H
    python manage.py download_history --years 3               # 3 years
    python manage.py download_history --symbol BTCUSDT --interval 4h
    python manage.py download_history --symbol SOLUSDT --years 2 --interval 1h

Binance klines limit: 1500 per request.
Rate limit: ~20 req/sec without API key, faster with key.
"""
import time
import logging
from datetime import datetime, timezone, timedelta

import requests
from django.core.management.base import BaseCommand
from django.conf import settings

logger = logging.getLogger(__name__)

BINANCE_REST = getattr(settings, 'BINANCE_REST_URL', 'https://fapi.binance.com')
INTERVALS    = ['1m', '5m', '15m', '1h', '4h']
MAX_PER_REQ  = 1500   # Binance max


class Command(BaseCommand):
    help = 'Download historical klines from Binance Futures'

    def add_arguments(self, parser):
        parser.add_argument('--symbol',   type=str, default=None,
                            help='Single symbol (e.g. BTCUSDT). Default: all watched pairs.')
        parser.add_argument('--interval', type=str, default='1h',
                            choices=INTERVALS,
                            help='Candle interval (default: 1h)')
        parser.add_argument('--years',   type=float, default=1.0,
                            help='Years of history to download (default: 1)')
        parser.add_argument('--all-intervals', action='store_true',
                            help='Download all intervals (1m 5m 15m 1h 4h). Warning: slow for 1m.')

    def handle(self, *args, **options):
        from ingester.models import WatchedPair, Candle
        from decimal import Decimal

        symbol_arg = options['symbol']
        interval   = options['interval']
        years      = options['years']
        all_ivs    = options['all_intervals']

        symbols  = [symbol_arg] if symbol_arg else WatchedPair.get_active_symbols()
        intervals = INTERVALS if all_ivs else [interval]

        end_ts   = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ts = int((datetime.now(timezone.utc) - timedelta(days=365 * years)).timestamp() * 1000)

        self.stdout.write(self.style.SUCCESS(
            f'Downloading {years}y history for {symbols} × {intervals}'
        ))

        for sym in symbols:
            for iv in intervals:
                self._download(sym, iv, start_ts, end_ts, Candle, Decimal)

        self.stdout.write(self.style.SUCCESS('Done ✅'))

    def _download(self, symbol, interval, start_ts, end_ts, Candle, Decimal):
        url       = f'{BINANCE_REST}/fapi/v1/klines'
        cursor    = start_ts
        total     = 0
        interval_ms = _interval_ms(interval)

        self.stdout.write(f'  {symbol} {interval} ...', ending='')

        while cursor < end_ts:
            params = {
                'symbol':    symbol,
                'interval':  interval,
                'startTime': cursor,
                'endTime':   min(cursor + MAX_PER_REQ * interval_ms, end_ts),
                'limit':     MAX_PER_REQ,
            }
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                rows = resp.json()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f' ERROR: {e}'))
                time.sleep(2)
                continue

            if not rows:
                break

            # Bulk upsert
            to_create = []
            for row in rows:
                ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
                to_create.append(Candle(
                    symbol=symbol, interval=interval, timestamp=ts,
                    open=Decimal(str(row[1])), high=Decimal(str(row[2])),
                    low=Decimal(str(row[3])),  close=Decimal(str(row[4])),
                    volume=Decimal(str(row[5])),
                    quote_volume=Decimal(str(row[7])),
                    taker_buy_volume=Decimal(str(row[9])),
                    taker_buy_quote_volume=Decimal(str(row[10])),
                    num_trades=int(row[8]),
                    is_closed=True,
                ))

            Candle.objects.bulk_create(
                to_create,
                update_conflicts=True,
                unique_fields=['symbol', 'interval', 'timestamp'],
                update_fields=['open','high','low','close','volume',
                               'quote_volume','taker_buy_volume',
                               'taker_buy_quote_volume','num_trades','is_closed'],
            )
            total  += len(rows)
            cursor  = rows[-1][0] + interval_ms
            self.stdout.write('.', ending='')
            self.stdout.flush()
            time.sleep(0.05)   # ~20 req/sec — stay under rate limit

        self.stdout.write(f' {total:,} candles')


def _interval_ms(interval: str) -> int:
    units = {'m': 60_000, 'h': 3_600_000, 'd': 86_400_000, 'w': 604_800_000}
    return int(interval[:-1]) * units[interval[-1]]
