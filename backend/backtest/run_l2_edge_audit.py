"""L2-EDGE audit: pure information test for Stream B (L2 order flow),
before any HYBRID/SMC work. No target_r, no stop-loss, no trailing, no
daily loss limit, no sizing, no reward/cost filter -- the only question
is whether L2-A/B/C signals carry short-horizon directional information
AT ALL, measured honestly against executable bid/ask (not mid), at
several latency assumptions.

Signal generation is UNCHANGED from the frozen L2-A/B/C definitions
(z>=2.0 on imbalance5/depth_imbalance_delta/depth5 changes) -- this
audit does not redesign the signals, only how their outcome is measured.
'ofi' is renamed depth_imbalance_delta throughout: it is a top-level
depth-change proxy, not classical add/cancel/trade order-flow imbalance.

Execution model:
  LONG:  entry = ask (at decision_ts + latency), exit = bid (at horizon)
  SHORT: entry = bid (at decision_ts + latency), exit = ask (at horizon)
  MFE/MAE computed along the executable exit-side price path within the
  horizon window, not on mid.
Latency variants: 0/100/250/500ms, looked up on a native-resolution
top-of-book change series (not the 500ms bars), so sub-500ms offsets are
genuinely resolved. If no TOB update exists in [requested_ts, requested_ts
+2s], the causal state as of `asof` is used and the gap is logged as
timestamp_error_ms.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from .download_l2_edge import get_bars_and_tob
from .download_l2_hist import download_l2_day
from .l2_signals import DAYS, SYMBOLS, generate_signals

LATENCIES_MS = (0, 100, 250, 500)
HORIZONS_S = (1, 3, 5, 10, 30)
ROUND_TRIP_FEE_BPS = 10.0  # 5bps taker each side, this project's base convention


def asof_row(tob_idx_i8, tob_bid, tob_ask, tob_mid, target_i8):
    """searchsorted-based causal asof lookup (fast, no pandas overhead per call)."""
    pos = np.searchsorted(tob_idx_i8, target_i8, side='right') - 1
    if pos < 0:
        return None
    return tob_bid[pos], tob_ask[pos], tob_mid[pos], tob_idx_i8[pos]


def window_path(tob_idx_i8, tob_bid, tob_ask, start_i8, end_i8):
    lo = np.searchsorted(tob_idx_i8, start_i8, side='left')
    hi = np.searchsorted(tob_idx_i8, end_i8, side='right')
    return tob_bid[lo:hi], tob_ask[lo:hi]


CHECKPOINT_PATH = Path('/tmp/sentinel-tick-cache/l2_edge_results.csv')
DONE_PATH = Path('/tmp/sentinel-tick-cache/l2_edge_done.txt')


def main():
    # Resume support: a 429 rate-limit mid-run previously lost an entire
    # ~20-minute pass because results were only accumulated in memory and
    # written once at the very end. Now each symbol-day's rows are
    # appended to CHECKPOINT_PATH immediately, and completed (symbol,day)
    # pairs are recorded in DONE_PATH so a rerun skips them instead of
    # re-downloading and re-parsing from scratch.
    done = set()
    if DONE_PATH.exists():
        done = set(DONE_PATH.read_text().splitlines())
        print(f'Resuming: {len(done)} symbol-days already completed, skipping those.', flush=True)

    for symbol in SYMBOLS:
        for day in DAYS:
            pair_key = f'{symbol}|{day}'
            if pair_key in done:
                print(f'skipping {symbol} {day} (already done)', flush=True)
                continue
            print(f'downloading/parsing {symbol} {day}...', flush=True)
            bars, tob = get_bars_and_tob(symbol, day, download_l2_day, bar_ms=500)
            if bars.empty or tob.empty:
                continue

            tob_idx_i8 = tob.index.asi8
            tob_bid = tob.best_bid.to_numpy()
            tob_ask = tob.best_ask.to_numpy()
            tob_mid = tob.mid.to_numpy()

            day_rows = []
            for mechanism in ('L2A', 'L2B', 'L2C'):
                signals = generate_signals(bars, symbol, mechanism)
                for sig in signals:
                    decision_i8 = sig['decision_ts'].value  # ns since epoch, but TOB index also ns -> compatible
                    side = sig['side']

                    entry0 = asof_row(tob_idx_i8, tob_bid, tob_ask, tob_mid, decision_i8)
                    if entry0 is None:
                        continue
                    mid_at_decision = entry0[2]

                    for lat_ms in LATENCIES_MS:
                        target_entry_i8 = decision_i8 + lat_ms * 1_000_000
                        entry = asof_row(tob_idx_i8, tob_bid, tob_ask, tob_mid, target_entry_i8)
                        if entry is None:
                            continue
                        entry_bid, entry_ask, entry_mid, entry_actual_i8 = entry
                        entry_price = entry_ask if side == 1 else entry_bid
                        ts_error_ms = (target_entry_i8 - entry_actual_i8) / 1_000_000

                        for horizon_s in HORIZONS_S:
                            target_exit_i8 = target_entry_i8 + int(horizon_s * 1_000_000_000)
                            exit_row = asof_row(tob_idx_i8, tob_bid, tob_ask, tob_mid, target_exit_i8)
                            if exit_row is None:
                                continue
                            exit_bid, exit_ask, exit_mid, _ = exit_row
                            exit_price = exit_bid if side == 1 else exit_ask

                            gross_bps = side * (exit_mid / entry_mid - 1.0) * 10_000
                            exec_bps = side * (exit_price / entry_price - 1.0) * 10_000

                            path_bid, path_ask = window_path(tob_idx_i8, tob_bid, tob_ask,
                                                              target_entry_i8, target_exit_i8)
                            if len(path_bid) == 0:
                                mfe = mae = exec_bps
                            else:
                                exit_path = path_bid if side == 1 else path_ask
                                signed_path = side * (exit_path / entry_price - 1.0) * 10_000
                                mfe = float(signed_path.max())
                                mae = float(signed_path.min())

                            day_rows.append({
                                'symbol': symbol, 'day': day, 'mechanism': mechanism, 'latency_ms': lat_ms,
                                'horizon_s': horizon_s, 'gross_bps': gross_bps, 'exec_bps': exec_bps,
                                'net_bps': exec_bps - ROUND_TRIP_FEE_BPS, 'mfe': mfe, 'mae': mae,
                                'ts_error_ms': ts_error_ms,
                            })

            # checkpoint: persist this symbol-day immediately, don't wait
            # for the whole 18-combination run to finish before saving.
            pd.DataFrame(day_rows).to_csv(
                CHECKPOINT_PATH, mode='a', index=False, header=not CHECKPOINT_PATH.exists())
            with open(DONE_PATH, 'a') as f:
                f.write(pair_key + '\n')
            print(f'  checkpointed {symbol} {day}: {len(day_rows)} rows', flush=True)

    df = pd.read_csv(CHECKPOINT_PATH)
    print(f'\nTotal (mechanism,horizon,latency) observations: {len(df)}')

    print('\n' + '=' * 110)
    print('L2-EDGE result: mechanism x horizon x latency=250ms (primary; 0/100/500ms in the saved CSV)')
    print('=' * 110)
    sub = df[df.latency_ms == 250]
    for (mech, h), g in sub.groupby(['mechanism', 'horizon_s']):
        hit = (g.exec_bps > 0).mean()
        print(f'{mech} h={h:>2d}s  n={len(g):>5d}  gross_mean={g.gross_bps.mean():>7.3f}  '
              f'exec_mean={g.exec_bps.mean():>7.3f}  net_mean={g.net_bps.mean():>7.3f}  '
              f'exec_median={g.exec_bps.median():>7.3f}  p25={g.exec_bps.quantile(.25):>7.3f}  '
              f'p75={g.exec_bps.quantile(.75):>7.3f}  hit_rate={hit*100:>5.1f}%  '
              f'MFE={g.mfe.mean():>7.3f}  MAE={g.mae.mean():>7.3f}  '
              f'MFE/|MAE|={g.mfe.mean()/abs(g.mae.mean()) if g.mae.mean() != 0 else float("nan"):>5.2f}')

    print('\n-- per symbol, h=5s, latency=250ms --')
    sub5 = sub[sub.horizon_s == 5]
    for (mech, sym), g in sub5.groupby(['mechanism', 'symbol']):
        print(f'{mech} {sym}: n={len(g):>4d} exec_mean={g.exec_bps.mean():>7.3f} '
              f'hit_rate={(g.exec_bps>0).mean()*100:>5.1f}%')

    print('\n-- timestamp error sanity (ms) --')
    print(df.ts_error_ms.describe())


if __name__ == '__main__':
    main()
