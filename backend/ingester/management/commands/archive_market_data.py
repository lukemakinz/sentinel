"""Archive complete UTC days of order book / aggTrades to Parquet; optional verify."""
import json

from django.core.management.base import BaseCommand

from ingester.archive import KINDS, archive_pending, read_manifest, verify


class Command(BaseCommand):
    help = 'Write missing daily Parquet archives (never deletes data).'

    def add_arguments(self, parser):
        parser.add_argument('--verify', action='store_true',
                            help='Re-check every manifest entry against file and DB.')

    def handle(self, *args, **options):
        written = {kind: archive_pending(kind) for kind in KINDS}
        for kind, entries in written.items():
            for e in entries:
                self.stdout.write(
                    f"{kind} {e['symbol']} {e['day']}: {e['rows']} rows, {e['bytes']} B, "
                    f"max gap {e['max_gap_seconds']}s, gaps>{e['gap_threshold_seconds']}s: "
                    f"{e['gaps_over_threshold']}")
        if options['verify']:
            bad = [key for key, entry in read_manifest().items() if not verify(entry)]
            self.stdout.write(json.dumps({'entries': len(read_manifest()), 'failed': bad}, default=str))
