from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
import tempfile
from unittest.mock import patch

import pyarrow.parquet as pq
from django.test import TestCase, override_settings
from django.utils import timezone

from ingester import archive
from ingester.models import AggTrade, OrderBookSnapshot
from ingester.tasks import prune_agg_trades, prune_order_book_snapshots


def snapshot(ts, update_id):
    return OrderBookSnapshot.objects.create(
        symbol='SOLUSDT', timestamp=ts, last_update_id=update_id,
        bids=[[99.9, 1.0]], asks=[[100.1, 2.0]], best_bid=Decimal('99.9'),
        best_ask=Decimal('100.1'), mid_price=Decimal('100'), spread_bps=Decimal('20'))


def trade(ts):
    return AggTrade.objects.create(symbol='SOLUSDT', timestamp=ts, price=Decimal('100'),
                                   quantity=Decimal('1'), usd_value=Decimal('100'),
                                   is_buyer_maker=False)


class MarketArchiveTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.override = override_settings(MARKET_ARCHIVE_DIR=self.tmp.name)
        self.override.enable()
        self.day = (timezone.now() - timedelta(days=20)).astimezone(dt_timezone.utc).date()
        base = datetime(self.day.year, self.day.month, self.day.day, 1, tzinfo=dt_timezone.utc)
        snapshot(base, 10)
        snapshot(base + timedelta(seconds=5), 12)
        snapshot(base + timedelta(seconds=125), 11)  # gap + update-id regression

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()

    def test_archive_writes_parquet_manifest_and_gap_report(self):
        entries = archive.archive_pending('order_book')

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['rows'], 3)
        self.assertEqual(entry['gaps_over_threshold'], 1)
        self.assertEqual(entry['update_id_regressions'], 1)
        table = pq.read_table(archive.archive_root() / entry['file'])
        self.assertEqual(table.column('bids').to_pylist()[0], [[99.9, 1.0]])
        self.assertTrue(archive.verify(entry))
        self.assertEqual(archive.archive_pending('order_book'), [])  # idempotent

    def test_prune_archives_first_then_deletes_and_file_survives(self):
        result = prune_order_book_snapshots()

        self.assertEqual(result['deleted'], 3)
        entry = archive.read_manifest()[('order_book', 'SOLUSDT', self.day.isoformat())]
        self.assertTrue(archive.verify(entry))  # pruned day: file is the source of truth

    def test_corrupt_archive_blocks_prune(self):
        archive.archive_pending('order_book')
        entry = archive.read_manifest()[('order_book', 'SOLUSDT', self.day.isoformat())]
        (archive.archive_root() / entry['file']).write_bytes(b'corrupt')
        # archive_pending would repair it, so simulate a failing writer.
        with patch('ingester.archive.archive_day', return_value=None):
            result = prune_order_book_snapshots()

        self.assertEqual(result['deleted'], 0)
        self.assertEqual(OrderBookSnapshot.objects.count(), 3)

    def test_recent_days_are_kept_and_aggtrades_follow_same_rule(self):
        trade(timezone.now() - timedelta(days=20))
        trade(timezone.now() - timedelta(hours=1))
        result = prune_agg_trades()

        self.assertEqual(result['deleted'], 1)
        self.assertEqual(AggTrade.objects.count(), 1)
        kinds = {key[0] for key in archive.read_manifest()}
        self.assertEqual(kinds, {'agg_trades'})
