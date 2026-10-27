"""Recompute the BENCH_AB_R2 paper-forward ledger and print its report."""
import json

from django.conf import settings
from django.core.management.base import BaseCommand

from backtest.paper_forward_ab import format_report, run_paper_forward


class Command(BaseCommand):
    help = 'Daily paper-forward of frozen BENCH_AB_R2 (no orders).'

    def add_arguments(self, parser):
        parser.add_argument('--cache', default=settings.PAPER_FORWARD_CACHE)
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        report = run_paper_forward(options['cache'])
        if options['json']:
            slim = {**report, 'scenarios': {k: {x: y for x, y in v.items() if x != 'days'}
                                            for k, v in report.get('scenarios', {}).items()}}
            self.stdout.write(json.dumps(slim, indent=2, default=str))
        else:
            self.stdout.write(format_report(report))
