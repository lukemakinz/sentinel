"""Streams a raw OKX L2 update file ONCE and produces two outputs:
  1. the same 500ms feature bars used for L2-A/B/C signal generation
     (unchanged definitions -- this run does not touch them), with
     'ofi' renamed to 'depth_imbalance_delta' (it is a top-level
     depth-change proxy, not classical add/cancel/trade OFI -- naming
     was overclaiming what was actually computed).
  2. a native-resolution top-of-book (TOB) series: one row EVERY TIME
     best_bid or best_ask actually changes (not sampled to 500ms) --
     needed because 100ms/250ms latency variants are meaningless if
     read off a 500ms-bucketed series (most sub-500ms offsets would
     silently collapse onto the same bucket).
"""
import gzip
import time
from pathlib import Path

import numpy as np
import pandas as pd

PARSED_CACHE = Path('/tmp/sentinel-tick-cache/parsed')


def get_bars_and_tob(symbol: str, day: str, download_fn, bar_ms: int = 500):
    """Cache the PARSED (small: bars ~170k rows, TOB ~0.1-1M rows)
    output, not just the raw download -- the raw file was deleted after
    every prior parse specifically to manage disk space, which meant any
    rerun (bug fix, crash, parameter tweak) re-hit Tardis.dev's CDN for
    the exact same day, and repeatedly doing that within one session is
    what triggered an escalating 429 rate limit that backoff alone could
    not clear. Once parsed, a symbol-day never needs downloading again.
    """
    PARSED_CACHE.mkdir(parents=True, exist_ok=True)
    bars_path = PARSED_CACHE / f'{symbol}_{day}_bars.parquet'
    tob_path = PARSED_CACHE / f'{symbol}_{day}_tob.parquet'
    if bars_path.exists() and tob_path.exists():
        return pd.read_parquet(bars_path), pd.read_parquet(tob_path)

    raw_path = download_fn(symbol, day)
    bars, tob = build_tob_and_bars(raw_path, bar_ms=bar_ms)
    Path(raw_path).unlink(missing_ok=True)
    if not bars.empty:
        bars.to_parquet(bars_path)
    if not tob.empty:
        tob.to_parquet(tob_path)
    return bars, tob


def build_tob_and_bars(path: str, bar_ms: int = 500):
    bids, asks = {}, {}
    bar_rows = []
    tob_ts, tob_bid, tob_ask = [], [], []
    first_ts = None
    next_bucket_ts = None
    last_best_bid, last_best_ask = None, None
    # Running best-bid/best-ask trackers -- recomputing max(bids)/min(asks)
    # from scratch on every one of ~150M rows (as a first draft did) costs
    # O(n) per row and made a single day take ~3600s instead of ~120s.
    # Incremental tracking is O(1) except on the rare row that removes the
    # CURRENT best level, where a fresh max/min is unavoidable.
    best_bid_price = None
    best_ask_price = None

    def snapshot_features(ts_us):
        if not bids or not asks:
            return None
        best_bid, best_ask = max(bids), min(asks)
        if best_ask <= best_bid:
            return None
        bid_qty_top, ask_qty_top = bids[best_bid], asks[best_ask]
        microprice = (best_bid * ask_qty_top + best_ask * bid_qty_top) / (bid_qty_top + ask_qty_top)
        mid = (best_bid + best_ask) / 2
        sorted_bids = sorted(bids.items(), key=lambda kv: -kv[0])
        sorted_asks = sorted(asks.items(), key=lambda kv: kv[0])
        depth1_bid, depth1_ask = bid_qty_top, ask_qty_top
        depth5_bid = sum(q for _, q in sorted_bids[:5])
        depth5_ask = sum(q for _, q in sorted_asks[:5])
        imbalance5 = (depth5_bid - depth5_ask) / (depth5_bid + depth5_ask) if (depth5_bid + depth5_ask) else 0
        return {
            'ts_us': ts_us, 'best_bid': best_bid, 'best_ask': best_ask, 'mid': mid,
            'microprice': microprice, 'spread_bps': (best_ask - best_bid) / best_bid * 10_000,
            'depth1_bid': depth1_bid, 'depth1_ask': depth1_ask,
            'depth5_bid': depth5_bid, 'depth5_ask': depth5_ask, 'imbalance5': imbalance5,
        }

    t0 = time.time()
    n = 0
    with gzip.open(path, 'rt') as f:
        f.readline()
        for line in f:
            n += 1
            parts = line.rstrip('\n').split(',')
            ts_us = int(parts[2])
            if first_ts is None:
                first_ts = ts_us
                next_bucket_ts = ts_us + bar_ms * 1000

            is_bid = parts[5] == 'bid'
            side_dict = bids if is_bid else asks
            price = float(parts[6])
            amount = float(parts[7])
            if amount == 0:
                side_dict.pop(price, None)
                if is_bid and price == best_bid_price:
                    best_bid_price = max(bids) if bids else None
                elif not is_bid and price == best_ask_price:
                    best_ask_price = min(asks) if asks else None
            else:
                side_dict[price] = amount
                if is_bid and (best_bid_price is None or price > best_bid_price):
                    best_bid_price = price
                elif not is_bid and (best_ask_price is None or price < best_ask_price):
                    best_ask_price = price

            if best_bid_price is not None and best_ask_price is not None and best_ask_price > best_bid_price:
                if best_bid_price != last_best_bid or best_ask_price != last_best_ask:
                    tob_ts.append(ts_us)
                    tob_bid.append(best_bid_price)
                    tob_ask.append(best_ask_price)
                    last_best_bid, last_best_ask = best_bid_price, best_ask_price

            if ts_us >= next_bucket_ts:
                feat = snapshot_features(ts_us)
                if feat is not None:
                    bar_rows.append(feat)
                next_bucket_ts = ts_us + bar_ms * 1000

    elapsed = time.time() - t0
    print(f'  parsed {n} rows in {elapsed:.1f}s -> {len(bar_rows)} bars, {len(tob_ts)} TOB changes', flush=True)

    bars = pd.DataFrame(bar_rows)
    if not bars.empty:
        bars['timestamp'] = pd.to_datetime(bars.ts_us, unit='us', utc=True)
        bars = bars.set_index('timestamp').drop(columns=['ts_us'])
        bars['depth_imbalance_delta'] = (bars.depth1_bid - bars.depth1_ask).diff()

    tob = pd.DataFrame({'best_bid': tob_bid, 'best_ask': tob_ask},
                        index=pd.to_datetime(np.array(tob_ts, dtype='int64'), unit='us', utc=True))
    tob['mid'] = (tob.best_bid + tob.best_ask) / 2
    return bars, tob
