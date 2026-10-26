"""CE-2 step 1: timestamp synchronization check. MUST run and be
inspected before any lead-lag hypothesis is tested -- a fixed/variable
offset between venues could fake a lead-lag signal that is really just
a timestamping artifact (exchange clock skew, ingestion latency
differences), not real price discovery lead.

Window: 2025-09-01 to 2025-09-06 (5 days), BTCUSDT/ETHUSDT/SOLUSDT --
a short discovery window (not the full 184-day dev window), consistent
with this project's practice of proving a mechanism cheaply before
scaling up data collection.

Method: build a synchronized 500ms grid (last trade price per bucket,
ffilled) per venue, compute 500ms log returns, then cross-correlate
Binance's return series against Bybit's and OKX's at lags -5s..+5s (in
500ms steps). A real lead-lag mechanism shows an asymmetric correlation
peak away from lag 0 with a specific sign; a synchronization artifact
typically shows up as a peak sitting near a small, STABLE offset
(e.g. a consistent ~200-500ms shift explainable by exchange-side
processing) that does not vary meaningfully across days.

OKX's daily archive is UTC+8-aligned (confirmed: the file labeled
2025-09-01 actually covers 2025-08-31 16:00 to 2025-09-01 16:00 UTC) --
handled here by fetching the adjacent day's file too and slicing by the
real UTC boundary.
"""
import numpy as np
import pandas as pd

from .download_ce2_trades import load_binance_trades_day, load_bybit_trades_day, load_okx_trades_day

SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
DAYS = ['2025-09-01', '2025-09-02', '2025-09-03', '2025-09-04', '2025-09-05', '2025-09-06']
BUCKET_MS = 500
MAX_LAG_S = 5
BINANCE_CACHE = '/tmp/sentinel-tick-cache'
CE2_CACHE = '/tmp/sentinel-ce2-cache'


def load_okx_range(symbol, start, end):
    """OKX daily files are UTC+8-aligned; fetch every OKX file-date that
    could overlap [start, end) in UTC and concatenate before slicing."""
    start_ts, end_ts = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    file_dates = pd.date_range(start_ts.normalize() - pd.Timedelta(days=1), end_ts.normalize() + pd.Timedelta(days=1), freq='D')
    frames = []
    for d in file_dates:
        try:
            frames.append(load_okx_trades_day(symbol, d.strftime('%Y-%m-%d'), CE2_CACHE))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=['price', 'quantity', 'side'])
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep='first')]
    return df[(df.index >= start_ts) & (df.index < end_ts)]


def to_bucket_grid(trades, start, end, bucket_ms=BUCKET_MS):
    start_ts, end_ts = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    trades = trades[(trades.index >= start_ts) & (trades.index < end_ts)]
    if trades.empty:
        return None
    grid = trades.price.resample(f'{bucket_ms}ms').last().ffill()
    return grid


def cross_correlation(a, b, max_lag_buckets):
    """corr(a[t], b[t+lag]) for lag in [-max_lag, max_lag]. Positive lag
    means b's return at t+lag is compared to a's return at t -- i.e. a
    LEADS b when the peak is at a positive lag with high correlation."""
    a, b = a.align(b, join='inner')
    a_ret, b_ret = a.diff().dropna(), b.diff().dropna()
    a_ret, b_ret = a_ret.align(b_ret, join='inner')
    results = {}
    for lag in range(-max_lag_buckets, max_lag_buckets + 1):
        if lag >= 0:
            x, y = a_ret.iloc[:len(a_ret) - lag] if lag else a_ret, b_ret.iloc[lag:] if lag else b_ret
        else:
            x, y = a_ret.iloc[-lag:], b_ret.iloc[:len(b_ret) + lag]
        n = min(len(x), len(y))
        if n < 50:
            results[lag] = np.nan
            continue
        x, y = x.iloc[:n].to_numpy(), y.iloc[:n].to_numpy()
        if x.std() == 0 or y.std() == 0:
            results[lag] = np.nan
            continue
        results[lag] = float(np.corrcoef(x, y)[0, 1])
    return results


def main():
    max_lag_buckets = int(MAX_LAG_S * 1000 / BUCKET_MS)

    for symbol in SYMBOLS:
        print(f'\n{"="*90}\n{symbol}\n{"="*90}')
        per_day_peaks = {'binance_bybit': [], 'binance_okx': []}
        for day in DAYS:
            start = day
            end = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            try:
                binance = load_binance_trades_day(symbol, day, BINANCE_CACHE)
                bybit = load_bybit_trades_day(symbol, day, CE2_CACHE)
                okx = load_okx_range(symbol, start, end)
            except Exception as exc:
                print(f'  {day}: SKIP ({str(exc)[:80]})')
                continue

            g_binance = to_bucket_grid(binance, start, end)
            g_bybit = to_bucket_grid(bybit, start, end)
            g_okx = to_bucket_grid(okx, start, end)
            if g_binance is None or g_bybit is None:
                print(f'  {day}: SKIP (missing grid)')
                continue

            corr_bb = cross_correlation(np.log(g_binance), np.log(g_bybit), max_lag_buckets)
            peak_lag_bb = max(corr_bb, key=lambda k: (corr_bb[k] if np.isfinite(corr_bb[k]) else -1))
            per_day_peaks['binance_bybit'].append((day, peak_lag_bb * BUCKET_MS, corr_bb[peak_lag_bb], corr_bb.get(0)))

            if g_okx is not None and len(g_okx.dropna()) > 100:
                corr_bo = cross_correlation(np.log(g_binance), np.log(g_okx), max_lag_buckets)
                peak_lag_bo = max(corr_bo, key=lambda k: (corr_bo[k] if np.isfinite(corr_bo[k]) else -1))
                per_day_peaks['binance_okx'].append((day, peak_lag_bo * BUCKET_MS, corr_bo[peak_lag_bo], corr_bo.get(0)))
            else:
                print(f'  {day}: OKX grid too sparse/missing, skipping OKX pair')

        print('\n  Binance-vs-Bybit peak lag per day (ms, +lag means Binance leads Bybit):')
        for day, lag_ms, peak_corr, corr0 in per_day_peaks['binance_bybit']:
            print(f'    {day}: peak_lag={lag_ms:+.0f}ms  peak_corr={peak_corr:.4f}  corr_at_lag0={corr0:.4f}')

        print('\n  Binance-vs-OKX peak lag per day (ms, +lag means Binance leads OKX):')
        for day, lag_ms, peak_corr, corr0 in per_day_peaks['binance_okx']:
            print(f'    {day}: peak_lag={lag_ms:+.0f}ms  peak_corr={peak_corr:.4f}  corr_at_lag0={corr0:.4f}')


if __name__ == '__main__':
    main()
