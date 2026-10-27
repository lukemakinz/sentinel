"""Durable daily Parquet archive of live order-book snapshots and aggTrades.

The live database keeps a rolling window; this archive is the long-term research
copy. One file per (kind, symbol, UTC day), zstd-compressed, plus one JSON line
per file in ``manifest.jsonl`` with row count, sha256 and a gap report. Pruning
deletes a day only after its archive is verified against the database.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from hashlib import sha256
import json
import logging
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

KINDS = ('order_book', 'agg_trades')
# Gap thresholds for the report: snapshots arrive every few seconds; trades on
# liquid symbols every second, so long silences point to a feed outage.
GAP_SECONDS = {'order_book': 60, 'agg_trades': 300}


def archive_root() -> Path:
    return Path(getattr(settings, 'MARKET_ARCHIVE_DIR', settings.BASE_DIR.parent / 'data' / 'archive'))


def _model(kind):
    from .models import AggTrade, OrderBookSnapshot
    return {'order_book': OrderBookSnapshot, 'agg_trades': AggTrade}[kind]


def _day_bounds(day: date):
    start = datetime.combine(day, time.min, tzinfo=dt_timezone.utc)
    return start, start + timedelta(days=1)


def _rows(kind: str, symbol: str, day: date) -> list[dict]:
    start, end = _day_bounds(day)
    query = _model(kind).objects.filter(
        symbol=symbol, timestamp__gte=start, timestamp__lt=end).order_by('timestamp', 'id')
    if kind == 'order_book':
        fields = ('timestamp', 'last_update_id', 'bids', 'asks', 'best_bid', 'best_ask',
                  'mid_price', 'spread_bps', 'bid_depth_5_usd', 'ask_depth_5_usd',
                  'bid_depth_20_usd', 'ask_depth_20_usd', 'imbalance_5', 'imbalance_20')
    else:
        fields = ('timestamp', 'price', 'quantity', 'usd_value', 'is_buyer_maker')
    out = []
    for values in query.values_list(*fields).iterator(chunk_size=5000):
        row = dict(zip(fields, values))
        for key, value in row.items():
            if key not in {'timestamp', 'bids', 'asks', 'is_buyer_maker', 'last_update_id'}:
                row[key] = float(value)
        out.append(row)
    return out


def gap_report(kind: str, rows: list[dict]) -> dict:
    stamps = [row['timestamp'] for row in rows]
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
    report = {
        'first': stamps[0].isoformat() if stamps else None,
        'last': stamps[-1].isoformat() if stamps else None,
        'max_gap_seconds': round(max(gaps), 3) if gaps else None,
        'gaps_over_threshold': sum(g > GAP_SECONDS[kind] for g in gaps),
        'gap_threshold_seconds': GAP_SECONDS[kind],
    }
    if kind == 'order_book':
        ids = [row['last_update_id'] for row in rows]
        report['update_id_regressions'] = sum(b < a for a, b in zip(ids, ids[1:]))
    return report


def _path(kind: str, symbol: str, day: date) -> Path:
    return archive_root() / kind / symbol / f'{day.isoformat()}.parquet'


def read_manifest() -> dict:
    """Latest manifest entry per (kind, symbol, day)."""
    path = archive_root() / 'manifest.jsonl'
    entries = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                entries[(entry['kind'], entry['symbol'], entry['day'])] = entry
    return entries


def _append_manifest(entry: dict) -> None:
    path = archive_root() / 'manifest.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        handle.write(json.dumps(entry, sort_keys=True) + '\n')


def archive_day(kind: str, symbol: str, day: date) -> dict | None:
    """Write one day's Parquet file; returns its manifest entry (None if empty)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = _rows(kind, symbol, day)
    if not rows:
        return None
    path = _path(kind, symbol, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    tmp = path.with_suffix('.parquet.tmp')
    pq.write_table(table, tmp, compression='zstd')
    tmp.replace(path)  # atomic: a crash never leaves a half-written file in place
    entry = {
        'kind': kind, 'symbol': symbol, 'day': day.isoformat(),
        'rows': len(rows), 'file': str(path.relative_to(archive_root())),
        'bytes': path.stat().st_size,
        'sha256': sha256(path.read_bytes()).hexdigest(),
        'written_at': timezone.now().isoformat(),
        **gap_report(kind, rows),
    }
    _append_manifest(entry)
    return entry


def verify(entry: dict) -> bool:
    """File exists, checksum matches and row count equals the database day."""
    import pyarrow.parquet as pq

    path = archive_root() / entry['file']
    if not path.exists() or sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        return False
    if pq.read_metadata(path).num_rows != entry['rows']:
        return False
    start, end = _day_bounds(date.fromisoformat(entry['day']))
    db_rows = _model(entry['kind']).objects.filter(
        symbol=entry['symbol'], timestamp__gte=start, timestamp__lt=end).count()
    # 0 = the day was already pruned; the file alone is then the source of truth.
    return db_rows in (0, entry['rows'])


def _db_days(kind: str, before: date) -> list[tuple[str, date]]:
    from django.db.models.functions import TruncDate

    start, _ = _day_bounds(before)
    pairs = (_model(kind).objects.filter(timestamp__lt=start)
             .annotate(day=TruncDate('timestamp', tzinfo=dt_timezone.utc))
             .values_list('symbol', 'day').distinct())
    return sorted(set(pairs))


def archive_pending(kind: str, today: date | None = None) -> list[dict]:
    """Archive every complete UTC day still in the DB that lacks a valid entry."""
    today = today or timezone.now().astimezone(dt_timezone.utc).date()
    manifest = read_manifest()
    written = []
    for symbol, day in _db_days(kind, before=today):
        entry = manifest.get((kind, symbol, day.isoformat()))
        if entry is not None and verify(entry):
            continue
        entry = archive_day(kind, symbol, day)
        if entry is not None:
            written.append(entry)
    return written


def safe_prune_cutoff(kind: str, cutoff: datetime) -> datetime:
    """Whole-day cutoff such that every day before it is verified-archived."""
    cutoff_day = cutoff.astimezone(dt_timezone.utc).date()
    manifest = read_manifest()
    for symbol, day in _db_days(kind, before=cutoff_day):
        entry = manifest.get((kind, symbol, day.isoformat()))
        if entry is None or not verify(entry):
            logger.warning('Prune held back: %s %s %s is not archived', kind, symbol, day)
            return _day_bounds(day)[0]
    return _day_bounds(cutoff_day)[0]
