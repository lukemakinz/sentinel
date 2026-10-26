"""Downloads Tardis.dev free-sample OKX incremental L2 order book data
(first day of each month, no API key needed) and reconstructs a causal
feature series: best bid/ask, spread, microprice, depth top-1/5/10,
queue imbalance, OFI (order flow imbalance proxy from level deltas).
Streams the gzip CSV (up to ~150M rows/day for BTC) without loading the
whole file into memory.
"""
import gzip
import time
from pathlib import Path

import pandas as pd
import requests

CACHE = '/tmp/sentinel-tick-cache'
TARDIS_SYMBOL = {'BTCUSDT': 'BTC-USDT-SWAP', 'ETHUSDT': 'ETH-USDT-SWAP', 'SOLUSDT': 'SOL-USDT-SWAP'}


def download_l2_day(symbol: str, day: str, max_retries: int = 5) -> str:
    y, m, d = day.split('-')
    inst = TARDIS_SYMBOL[symbol]
    path = Path(CACHE) / f'okx_l2_{symbol}_{day}.csv.gz'
    if path.exists():
        return str(path)
    url = f'https://datasets.tardis.dev/v1/okex-swap/incremental_book_L2/{y}/{m}/{d}/{inst}.csv.gz'
    # After ~9 large (0.9-2GB) downloads in one session, Tardis.dev's CDN
    # started returning 429 (Too Many Requests) mid-run, losing all
    # progress since results were only accumulated in-memory -- retry
    # with exponential backoff instead of letting one rate-limit response
    # crash a 20+ minute run.
    for attempt in range(max_retries):
        try:
            with requests.get(url, stream=True, timeout=300) as r:
                if r.status_code == 429:
                    raise requests.exceptions.HTTPError('429', response=r)
                r.raise_for_status()
                tmp_path = path.with_suffix('.partial')
                with open(tmp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                tmp_path.rename(path)
            time.sleep(3)  # small proactive gap between large downloads, not just reactive backoff
            return str(path)
        except requests.exceptions.HTTPError as exc:
            if attempt == max_retries - 1:
                raise
            wait = 15 * (2 ** attempt)
            print(f'  download {symbol} {day} failed ({exc}), retry {attempt+1}/{max_retries} '
                  f'in {wait}s...', flush=True)
            time.sleep(wait)
    raise RuntimeError('unreachable')


def build_feature_bars(path: str, bar_ms: int = 500, max_seconds: float = None) -> pd.DataFrame:
    """Streams the raw L2 update file, reconstructs the book causally,
    and emits one feature row per bar_ms bucket boundary (using the book
    state as of the last update at/before that boundary -- no lookahead)."""
    bids, asks = {}, {}
    prev_bid_top, prev_ask_top = None, None
    rows = []
    first_ts = None
    next_bucket_ts = None

    def snapshot_features(ts_us):
        if not bids or not asks:
            return None
        best_bid = max(bids)
        best_ask = min(asks)
        if best_ask <= best_bid:
            return None
        spread_bps = (best_ask - best_bid) / best_bid * 10_000
        bid_qty_top = bids[best_bid]
        ask_qty_top = asks[best_ask]
        microprice = (best_bid * ask_qty_top + best_ask * bid_qty_top) / (bid_qty_top + ask_qty_top)
        mid = (best_bid + best_ask) / 2

        sorted_bids = sorted(bids.items(), key=lambda kv: -kv[0])
        sorted_asks = sorted(asks.items(), key=lambda kv: kv[0])
        depth1_bid = bid_qty_top
        depth1_ask = ask_qty_top
        depth5_bid = sum(q for _, q in sorted_bids[:5])
        depth5_ask = sum(q for _, q in sorted_asks[:5])
        depth10_bid = sum(q for _, q in sorted_bids[:10])
        depth10_ask = sum(q for _, q in sorted_asks[:10])

        imbalance1 = (depth1_bid - depth1_ask) / (depth1_bid + depth1_ask) if (depth1_bid + depth1_ask) else 0
        imbalance5 = (depth5_bid - depth5_ask) / (depth5_bid + depth5_ask) if (depth5_bid + depth5_ask) else 0
        imbalance10 = (depth10_bid - depth10_ask) / (depth10_bid + depth10_ask) if (depth10_bid + depth10_ask) else 0

        return {
            'ts_us': ts_us, 'best_bid': best_bid, 'best_ask': best_ask, 'mid': mid,
            'microprice': microprice, 'spread_bps': spread_bps,
            'depth1_bid': depth1_bid, 'depth1_ask': depth1_ask,
            'depth5_bid': depth5_bid, 'depth5_ask': depth5_ask,
            'depth10_bid': depth10_bid, 'depth10_ask': depth10_ask,
            'imbalance1': imbalance1, 'imbalance5': imbalance5, 'imbalance10': imbalance10,
        }

    t0 = time.time()
    n = 0
    with gzip.open(path, 'rt') as f:
        header = f.readline()
        for line in f:
            n += 1
            parts = line.rstrip('\n').split(',')
            ts_us = int(parts[2])
            if first_ts is None:
                first_ts = ts_us
                next_bucket_ts = ts_us + bar_ms * 1000
            if max_seconds is not None and (ts_us - first_ts) / 1_000_000 > max_seconds:
                break

            side_dict = bids if parts[5] == 'bid' else asks
            price = float(parts[6])
            amount = float(parts[7])
            if amount == 0:
                side_dict.pop(price, None)
            else:
                side_dict[price] = amount

            if ts_us >= next_bucket_ts:
                feat = snapshot_features(ts_us)
                if feat is not None:
                    rows.append(feat)
                next_bucket_ts = ts_us + bar_ms * 1000

    elapsed = time.time() - t0
    print(f'  parsed {n} rows in {elapsed:.1f}s -> {len(rows)} feature bars', flush=True)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df['timestamp'] = pd.to_datetime(df.ts_us, unit='us', utc=True)
    df = df.set_index('timestamp').drop(columns=['ts_us'])
    # OFI proxy: change in (bid depth - ask depth) at top level between bars, causal by construction
    # A top-level depth-CHANGE proxy, not classical add/cancel/trade OFI --
    # named honestly to match l2_signals.py's expected column.
    df['depth_imbalance_delta'] = (df.depth1_bid - df.depth1_ask).diff()
    return df
