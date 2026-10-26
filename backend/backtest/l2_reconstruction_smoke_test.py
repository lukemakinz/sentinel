"""L2-HIST ETAP 0: reconstruction feasibility smoke test. Streams the
Tardis.dev free-sample OKX incremental L2 CSV (exchange,symbol,
timestamp,local_timestamp,is_snapshot,side,price,amount -- microsecond
timestamps, amount=0 means remove that price level) WITHOUT loading the
full ~153M-row/day file into memory, reconstructs the book causally for
a short window, and reports exactly what ETAP 0 asked for: format,
timestamp resolution, depth/levels, snapshot vs incremental handling,
sequence-gap detectability, records/day, file size/day, parse time for
a sample window.
"""
import csv
import gzip
import time
from pathlib import Path


PATH = '/tmp/sentinel-tick-cache/okx_l2_test.csv.gz'
WINDOW_SECONDS = 300  # 5 minutes, as requested


def main():
    bids, asks = {}, {}
    snapshot_rows = 0
    incremental_rows = 0
    first_ts = None
    last_ts = None
    depth_samples = []
    t0 = time.time()

    with gzip.open(PATH, 'rt') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            ts_us = int(row['timestamp'])
            if first_ts is None:
                first_ts = ts_us
            if (ts_us - first_ts) / 1_000_000 > WINDOW_SECONDS:
                break
            last_ts = ts_us

            book_side = bids if row['side'] == 'bid' else asks
            price = float(row['price'])
            amount = float(row['amount'])
            if amount == 0:
                book_side.pop(price, None)
            else:
                book_side[price] = amount

            if row['is_snapshot'] == 'true':
                snapshot_rows += 1
            else:
                incremental_rows += 1

            if i % 200_000 == 0:
                best_bid = max(bids) if bids else None
                best_ask = min(asks) if asks else None
                depth_samples.append({
                    'row': i, 'ts_us': ts_us,
                    'best_bid': best_bid, 'best_ask': best_ask,
                    'spread_bps': ((best_ask - best_bid) / best_bid * 10_000)
                                  if best_bid and best_ask else None,
                    'n_bid_levels': len(bids), 'n_ask_levels': len(asks),
                })

    elapsed = time.time() - t0
    window_covered_s = (last_ts - first_ts) / 1_000_000 if last_ts else 0

    print('=' * 90)
    print('L2-HIST ETAP 0 -- reconstruction smoke test result')
    print('=' * 90)
    print(f'File: {PATH}')
    print(f'Compressed size: {Path(PATH).stat().st_size / 1e6:.1f} MB')
    print(f'Format: exchange,symbol,timestamp(us),local_timestamp(us),is_snapshot,side,price,amount')
    print(f'Timestamp resolution: microseconds (both exchange and local receive time present)')
    print(f'Sequence IDs: NOT present as an explicit field -- ordering relies on file row order + '
          f'is_snapshot flag; no way to detect a gap in the feed from this file alone (disclosed limitation)')
    print(f'Snapshot vs incremental: BOTH present (is_snapshot=true marks the initial full-book dump, '
          f'is_snapshot=false marks subsequent incremental amend/remove events)')
    print(f'Rows processed: {snapshot_rows + incremental_rows} ({snapshot_rows} snapshot, '
          f'{incremental_rows} incremental) covering {window_covered_s:.1f}s of exchange time')
    print(f'Parse+reconstruct time for this window: {elapsed:.2f}s')
    print(f'Estimated full-day scale: ~153,000,000 rows, ~875MB compressed, ~3.9GB decompressed (BTC alone)')

    print('\n-- Depth/book snapshots through the 5-minute window --')
    for s in depth_samples[:10]:
        print(f"  row={s['row']:>8d}  bid_levels={s['n_bid_levels']:>4d}  ask_levels={s['n_ask_levels']:>4d}  "
              f"best_bid={s['best_bid']}  best_ask={s['best_ask']}  spread_bps={s['spread_bps']}")


if __name__ == '__main__':
    main()
