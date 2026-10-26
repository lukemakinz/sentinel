"""M3 AUDIT -- one final pass on M3's existing event/tick data, no new
filters, no threshold changes. Answers the question properly before M3
is closed for good:
  1. coverage: usable/total events per symbol x month
  2. MFE/MAE (from the real decision point, t+3s) at 10/30/60/120/300s
  3. percentiles (p05/p25/p50/p75/p95) of forward returns, not just
     median/mean
  4. bootstrap CI on mean forward return per classification
  5. a MATCHED PLACEBO: same symbol-days, random non-event 15m-aligned
     timestamps (same count as real events per symbol), same tick
     analysis pipeline -- if LQX-conditioned events don't look
     different from ordinary moments, that is the final word.
  6. a manual timestamp sanity check (first-tick / decision / target)
     on a few real events, printed for inspection.

If MFE/MAE and the placebo comparison don't show a asymmetry clearly
covering costs, M3 is closed for good -- no more filtering.
"""
import numpy as np
import pandas as pd

from .download_agg_trades import load_agg_trades_day
from .run_m3_tick_confirmation import (
    CONFIRM_WINDOW_S, TICK_CACHE, VELOCITY_BASELINE_S, collect_fresh_flow_events,
)

MFE_MAE_HORIZONS_S = (10, 30, 60, 120, 300)
BOOTSTRAP_N = 5000


def load_cached_days():
    """Only symbol-days already downloaded and checksum-complete."""
    import glob
    import os
    available = {}
    for zpath in glob.glob(f'{TICK_CACHE}/*/*-aggTrades-*.zip'):
        checksum = zpath + '.CHECKSUM'
        if not os.path.exists(checksum):
            continue
        base = os.path.basename(zpath)
        symbol = base.split('-aggTrades-')[0]
        day = base.split('-aggTrades-')[1].replace('.zip', '')
        available.setdefault(symbol, set()).add(day)
    return available


def analyze_window(trades, ts, move_side, event_close):
    """Same metric computation as run_m3_tick_confirmation.analyze_event,
    but also returns MFE/MAE at multiple horizons and full tick path."""
    baseline_start = ts - pd.Timedelta(seconds=VELOCITY_BASELINE_S)
    baseline = trades[(trades.index > baseline_start) & (trades.index <= ts)]
    if len(baseline) < 5:
        return None

    confirm_end = ts + pd.Timedelta(seconds=CONFIRM_WINDOW_S)
    confirm = trades[(trades.index > ts) & (trades.index <= confirm_end)]
    if len(confirm) < 2:
        return None

    aligned_vol = confirm.quantity[(confirm.is_buyer_maker == (move_side < 0))].sum()
    total_vol = confirm.quantity.sum()
    if total_vol <= 0:
        return None
    flow_alignment = aligned_vol / total_vol
    decision_price = confirm.price.iloc[-1]
    price_response_bps = move_side * (decision_price / event_close - 1.0) * 10_000

    if flow_alignment > 0.5 and price_response_bps > 0:
        classification = 'CONTINUATION'
    elif flow_alignment > 0.5 and price_response_bps <= 0:
        classification = 'ABSORPTION'
    else:
        classification = 'OPPOSITE_FLOW'

    max_h = max(MFE_MAE_HORIZONS_S)
    window = trades[(trades.index > confirm_end) &
                     (trades.index <= confirm_end + pd.Timedelta(seconds=max_h))]
    result = {'classification': classification, 'decision_ts': confirm_end}
    for h in MFE_MAE_HORIZONS_S:
        sub = window[window.index <= confirm_end + pd.Timedelta(seconds=h)]
        if sub.empty:
            result[f'fwd_{h}s'] = np.nan
            result[f'mfe_{h}s'] = np.nan
            result[f'mae_{h}s'] = np.nan
            continue
        signed_path = move_side * (sub.price.to_numpy() / decision_price - 1.0) * 10_000
        result[f'fwd_{h}s'] = signed_path[-1]
        result[f'mfe_{h}s'] = signed_path.max()   # best case seen along the path
        result[f'mae_{h}s'] = signed_path.min()   # worst case seen along the path
    return result


def bootstrap_ci(values, n=BOOTSTRAP_N, seed=7):
    values = np.asarray(values)
    if len(values) < 10:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = [rng.choice(values, size=len(values), replace=True).mean() for _ in range(n)]
    return (float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975)))


def main():
    events_by_symbol = collect_fresh_flow_events()
    available = load_cached_days()

    real_rows = []
    placebo_rows = []
    coverage = {}
    timestamp_samples = []

    for symbol, events in events_by_symbol.items():
        days_available = available.get(symbol, set())
        month_total, month_usable = {}, {}
        events_by_day = {}
        for e in events:
            day = e['timestamp'].strftime('%Y-%m-%d')
            month = day[:7]
            month_total[month] = month_total.get(month, 0) + 1
            events_by_day.setdefault(day, []).append(e)
            if day not in days_available:
                continue
            trades = load_agg_trades_day(symbol, day, TICK_CACHE)
            r = analyze_window(trades, e['timestamp'], e['move_side'], e['close'])
            if r is None:
                continue
            month_usable[month] = month_usable.get(month, 0) + 1
            r.update({'symbol': symbol, 'day': day})
            real_rows.append(r)
            if len(timestamp_samples) < 5:
                timestamp_samples.append({
                    'symbol': symbol, 'event_bar_close': e['timestamp'],
                    'decision_ts (t+3s)': r['decision_ts'],
                    'target_10s_ts': r['decision_ts'] + pd.Timedelta(seconds=10),
                })

        coverage[symbol] = {m: (month_usable.get(m, 0), month_total[m]) for m in sorted(month_total)}

        # matched placebo: same symbol-days, random 15m-aligned non-event timestamps
        rng = np.random.default_rng(hash(symbol) % (2**31))
        placebo_needed = len(events)
        placebo_found = 0
        attempts = 0
        usable_days = [d for d in events_by_day if d in days_available]
        while placebo_found < placebo_needed and attempts < placebo_needed * 20 and usable_days:
            attempts += 1
            day = usable_days[rng.integers(0, len(usable_days))]
            trades = load_agg_trades_day(symbol, day, TICK_CACHE)
            minute_of_day = int(rng.integers(0, 24 * 4)) * 15  # random 15m slot
            ts = pd.Timestamp(day, tz='UTC') + pd.Timedelta(minutes=minute_of_day)
            event_tss = {e['timestamp'] for e in events_by_day[day]}
            if any(abs((ts - ets).total_seconds()) < 900 for ets in event_tss):
                continue  # too close to a real event, not a clean placebo
            around = trades[(trades.index > ts - pd.Timedelta(minutes=1)) &
                            (trades.index <= ts)]
            if len(around) < 3:
                continue
            pseudo_close = around.price.iloc[-1]
            pseudo_side = 1 if around.price.iloc[-1] >= around.price.iloc[0] else -1
            r = analyze_window(trades, ts, pseudo_side, pseudo_close)
            if r is None:
                continue
            r.update({'symbol': symbol, 'day': day})
            placebo_rows.append(r)
            placebo_found += 1

        print(symbol, 'done:', len([r for r in real_rows if r['symbol'] == symbol]),
              'real,', placebo_found, 'placebo', flush=True)

    real_df = pd.DataFrame(real_rows)
    placebo_df = pd.DataFrame(placebo_rows)

    print('\n' + '=' * 90)
    print('1) COVERAGE per symbol x month (usable/total)')
    print('=' * 90)
    for symbol, months in coverage.items():
        row = '  '.join(f'{m}:{u}/{t}' for m, (u, t) in months.items())
        print(f'{symbol:9s} {row}')

    print('\n' + '=' * 90)
    print('2)+3) MFE/MAE and percentiles by classification (real events)')
    print('=' * 90)
    for cls, g in real_df.groupby('classification'):
        print(f'\n-- {cls} (n={len(g)}) --')
        for h in MFE_MAE_HORIZONS_S:
            fwd = g[f'fwd_{h}s'].dropna()
            mfe = g[f'mfe_{h}s'].dropna()
            mae = g[f'mae_{h}s'].dropna()
            if len(fwd) < 10:
                print(f'  +{h:>3d}s: insufficient data')
                continue
            ci = bootstrap_ci(fwd.to_numpy())
            print(f'  +{h:>3d}s  fwd: p05={fwd.quantile(.05):>6.2f} p25={fwd.quantile(.25):>6.2f} '
                  f'p50={fwd.quantile(.5):>6.2f} p75={fwd.quantile(.75):>6.2f} p95={fwd.quantile(.95):>6.2f} '
                  f'mean={fwd.mean():>6.2f} 95%CI=[{ci[0]:.2f},{ci[1]:.2f}]  '
                  f'| MFE mean={mfe.mean():>6.2f} MAE mean={mae.mean():>6.2f}')

    print('\n' + '=' * 90)
    print('5) MATCHED PLACEBO (same symbol-days, random non-event 15m timestamps)')
    print('=' * 90)
    print(f'Placebo sample: n={len(placebo_df)}')
    for h in MFE_MAE_HORIZONS_S:
        fwd = placebo_df[f'fwd_{h}s'].dropna()
        if len(fwd) < 10:
            continue
        ci = bootstrap_ci(fwd.to_numpy())
        print(f'  +{h:>3d}s  fwd: p50={fwd.quantile(.5):>6.2f} mean={fwd.mean():>6.2f} '
              f'95%CI=[{ci[0]:.2f},{ci[1]:.2f}]  (n={len(fwd)})')

    print('\n' + '=' * 90)
    print('6) TIMESTAMP SANITY CHECK (sample events)')
    print('=' * 90)
    for s in timestamp_samples:
        print(' ', s)


if __name__ == '__main__':
    main()
