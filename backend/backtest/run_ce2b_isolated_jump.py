"""CE-2 step 5+6: CE2-B only (CE2-A ruled out by the sync check itself --
peak cross-correlation lag was exactly 0ms on all 16/17 symbol-day-venue
pairs tested, so there is no consensus-leads-Binance timing edge to
exploit; see run_ce2_sync_check.py output).

CE2-B: Binance makes an isolated jump relative to the simultaneous
Bybit/OKX consensus -> fade Binance back toward consensus.

Step 5 (measure first, no threshold assumed): build a 500ms grid per
venue, compute Binance's residual vs the OKX/Bybit average ("consensus")
at each bucket, report the raw distribution, then MFE/MAE and catch-up
half-life for whatever the natural extreme deciles look like -- BEFORE
picking an entry threshold.

Step 6: whatever threshold the step-5 numbers actually support, run the
full costed $250 execute_cluster backtest (base + stress), reported in
trades/day, PF, expectancy_R, net PnL $, $/day, max DD -- not bps only.
"""
from collections import Counter
from dataclasses import replace

import numpy as np
import pandas as pd
import talib

from l1_filter.scalp_strategy import ScalpConfig
from .cluster_scalp_simulator import execute_cluster
from .download_ce2_trades import load_binance_trades_day, load_bybit_trades_day
from .run_ce2_sync_check import BUCKET_MS, DAYS, SYMBOLS, load_okx_range, to_bucket_grid
from .scalp_data import load_archives

BINANCE_CACHE = '/tmp/sentinel-tick-cache'
CE2_CACHE = '/tmp/sentinel-ce2-cache'
BINANCE_SCALP_CACHE = '/tmp/sentinel-scalp-cache'


def build_residual_series(symbol, day):
    start, end = day, (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    binance = load_binance_trades_day(symbol, day, BINANCE_CACHE)
    bybit = load_bybit_trades_day(symbol, day, CE2_CACHE)
    okx = load_okx_range(symbol, start, end)

    g_b = to_bucket_grid(binance, start, end)
    g_y = to_bucket_grid(bybit, start, end)
    g_x = to_bucket_grid(okx, start, end)
    if g_b is None or g_y is None:
        return None
    frame = pd.DataFrame({'binance': g_b, 'bybit': g_y})
    if g_x is not None and len(g_x.dropna()) > 100:
        frame['okx'] = g_x
    frame = frame.dropna()
    if frame.empty:
        return None
    consensus_cols = [c for c in ('bybit', 'okx') if c in frame.columns]
    frame['consensus'] = frame[consensus_cols].mean(axis=1)
    frame['residual_bps'] = (frame.binance / frame.consensus - 1.0) * 10_000
    return frame


def main():
    print('=' * 90)
    print('STEP 5: raw residual distribution (Binance vs Bybit/OKX consensus, 500ms grid)')
    print('=' * 90)
    all_residuals = []
    for symbol in SYMBOLS:
        symbol_residuals = []
        for day in DAYS:
            frame = build_residual_series(symbol, day)
            if frame is None:
                continue
            symbol_residuals.append(frame.residual_bps)
        if not symbol_residuals:
            continue
        combined = pd.concat(symbol_residuals)
        all_residuals.append(combined)
        print(f'\n{symbol} (n={len(combined)} buckets):')
        print(f'  std={combined.std():.3f}bps  '
              f'p50={combined.abs().median():.3f}  p90={combined.abs().quantile(.9):.3f}  '
              f'p99={combined.abs().quantile(.99):.3f}  p999={combined.abs().quantile(.999):.3f}  '
              f'max={combined.abs().max():.3f}bps')
        for thr in (5, 10, 15, 20, 30):
            share = (combined.abs() >= thr).mean()
            per_day = (combined.abs() >= thr).sum() / len(DAYS)
            print(f'    |residual|>={thr:>3.0f}bps: {share*100:.4f}% of buckets, ~{per_day:.1f} buckets/day')


if __name__ == '__main__':
    main()
