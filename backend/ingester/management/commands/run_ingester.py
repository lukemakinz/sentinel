"""
Management command to run the Binance WebSocket ingester.
Usage: python manage.py run_ingester
"""
import asyncio
import logging
import signal

from django.core.management.base import BaseCommand

from ingester.binance_ws import BinanceWebSocketClient
from ingester.tasks import backfill_candles

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Start the Binance Futures WebSocket data ingester'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🏴‍☠️ SENTINEL Ingester starting...'))

        # Backfill in background (don't block WebSocket start)
        self.stdout.write('Scheduling historical candle backfill...')
        try:
            backfill_candles.delay()   # async via Celery
        except Exception:
            backfill_candles()         # fallback: sync if Celery not ready

        # Start WebSocket
        client = BinanceWebSocketClient()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Handle graceful shutdown
        def shutdown(sig, frame):
            self.stdout.write(self.style.WARNING(f'\nReceived {sig}, shutting down...'))
            client.stop()

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        try:
            self.stdout.write(self.style.SUCCESS('WebSocket streaming started'))
            loop.run_until_complete(client.connect())
        except KeyboardInterrupt:
            client.stop()
        finally:
            loop.close()
            self.stdout.write(self.style.SUCCESS('Ingester stopped'))
