"""Daily S121 forward paper tracker (new-listing short with funding guard)."""
import json

from django.core.management.base import BaseCommand

from backtest.s121_listing_forward import run


class Command(BaseCommand):
    help = 'Recompute the S121 forward paper ledger from Binance public data (no orders).'

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(run(), indent=2))
