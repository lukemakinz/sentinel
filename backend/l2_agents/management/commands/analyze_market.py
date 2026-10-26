"""Build and optionally AI-adjudicate a read-only market snapshot."""
import json

from django.core.management.base import BaseCommand, CommandError

from l2_agents.auction_service import analyze_symbol


class Command(BaseCommand):
    help = 'Analyze one futures symbol in shadow mode; never places an order.'

    def add_arguments(self, parser):
        parser.add_argument('symbol', help='Futures symbol, for example BTCUSDT')
        parser.add_argument(
            '--ai', action='store_true',
            help='Call the configured AI adjudicator after deterministic preflight.',
        )
        parser.add_argument(
            '--no-save', action='store_true',
            help='Print the result without writing an AuctionAnalysis audit row.',
        )
        parser.add_argument('--compact', action='store_true', help='Print compact JSON.')

    def handle(self, *args, **options):
        symbol = options['symbol'].strip().upper()
        if not symbol.isalnum() or len(symbol) > 20:
            raise CommandError('Invalid symbol')

        output = analyze_symbol(
            symbol,
            use_ai=options['ai'],
            persist=not options['no_save'],
            deduplicate_bar=False,
        )
        indent = None if options['compact'] else 2
        # Preserve insertion order: analysis_cost is intentionally the final field.
        self.stdout.write(json.dumps(output, indent=indent, default=str))
