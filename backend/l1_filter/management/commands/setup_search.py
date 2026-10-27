"""Scan altcoins for the OB Liquidity Reversal checklist; never places orders."""
from dataclasses import replace
import json

from django.core.management.base import BaseCommand

from l1_filter.setup_search import CHECKLIST, SetupSearchConfig, run_setup_search


class Command(BaseCommand):
    help = 'Setup search: OB Liquidity Reversal checklist across Binance altcoin perpetuals.'

    def add_arguments(self, parser):
        parser.add_argument('--symbol', action='append', dest='symbols',
                            help='Scan only this symbol; repeat for more.')
        parser.add_argument('--min-volume', type=float, default=20_000_000,
                            help='Minimum 24h quote volume in USD (default 20M).')
        parser.add_argument('--max-symbols', type=int, default=60)
        parser.add_argument('--side', choices=['long', 'short', 'both'], default='both')
        parser.add_argument('--all', action='store_true',
                            help='Also list symbols with no setup.')
        parser.add_argument('--json', action='store_true', help='Print raw JSON.')

    def handle(self, *args, **options):
        config = replace(SetupSearchConfig(),
                         min_quote_volume_usd=options['min_volume'],
                         max_symbols=options['max_symbols'])
        symbols = [s.upper() for s in options['symbols']] if options['symbols'] else None
        report = run_setup_search(config, symbols)
        rows = report['rows']
        if options['side'] != 'both':
            rows = [r for r in rows if r['side'] == options['side'].upper()]
        if not options['all']:
            rows = [r for r in rows if r['status'] != 'NO_SETUP']
        report['rows'] = rows
        if options['json']:
            self.stdout.write(json.dumps(report, indent=2, default=str))
            return

        self.stdout.write(f"Setup search {report['as_of']} — {report['universe']} rynków")
        self.stdout.write(self.style.WARNING(report['warning']))
        if not rows:
            self.stdout.write('Brak setupów w toku.')
        for row in rows:
            marks = ''.join('✓' if row['checklist'][k] else '·' for k in CHECKLIST)
            self.stdout.write(
                f"\n{row['symbol']:<14} {row['side']:<5} {row['status']:<16} "
                f"{row['score']}/7 [{marks}]  cena {row['price']}")
            self.stdout.write(f"  → {row['next']}")
            if row.get('absorption'):
                self.stdout.write(f"  absorpcja: {row['absorption']}")
        for error in report['errors']:
            self.stderr.write(f'błąd: {error}')
