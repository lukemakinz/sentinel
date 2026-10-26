"""ALPHA -> EXECUTION AUDIT for L2A. Diagnosis only -- no threshold,
entry, stop or exit changes. Reuses already-cached parsed L2 data (no
re-download): get_bars_and_tob returns the same parquet the completed
L2-EDGE run produced.

For every L2A candidate signal (all 18 symbol-days, BTC+ETH+SOL -- the
frozen universe; BTC+ETH is reported ONLY as a diagnostic subset, never
as the primary result, since dropping SOL only after seeing its result
would be post-hoc selection) this reconstructs four legs:

  A. decision -> decision+5s              (raw mid-to-mid drift)
  B. decision -> fill                     (cost of actually getting in)
  C. fill -> decision+5s                  (alpha remaining after paying to get in)
  D. fill -> exit                         (MICRO-SIM's own dynamic exit: target/stop/trail/timeout)

Two fill models are compared for leg B/C, so it's explicit which costs
L2-EDGE's exec_bps already contained and which MICRO-SIM's modeled
slippage represents instead of:
  - REAL fill: crosses the actual OKX best bid/ask from the native-
    resolution TOB series, at decision_ts + 0ms (MICRO-SIM has no
    explicit decision->order latency model -- it fills within the same
    500ms bar the signal occurs on, so 0ms is the fair comparison; 250ms
    is reported alongside as a more conservative reaction-time estimate).
    This is the SAME construction as run_l2_edge_audit.py's entry_price,
    so it already includes the real spread. No fee is added here (fees
    are accounted separately, once, in the MICRO-SIM $ numbers).
  - MICRO-SIM fill: bars['mid'] * (1 +/- slippage_bps/10000), i.e. mid
    plus a flat 2bps modeled slippage proxy standing in for spread+impact
    (MICRO-SIM has no real order book, only a mid series).
"""
from pathlib import Path

import numpy as np
import pandas as pd

from .download_l2_edge import get_bars_and_tob
from .download_l2_hist import download_l2_day
from .l2_signals import DAYS, SYMBOLS
from .l2_signals import generate_signals as generate_l2_signals
from .micro_sim import MicroSimConfig, execute_l2_single_symbol
from .run_l2_edge_audit import asof_row, window_path
from .run_l2_microsim import STOP_VOL_MULT, VOL_WINDOW, build_execution_signals

MECHANISM = 'L2A'
HORIZON_5S_NS = 5_000_000_000
R_CHECKPOINTS = (0.25, 0.5, 1.0)


def compute_vol_unit(bars):
    ret_60s = np.log(bars.mid).diff(120)
    return ret_60s.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std() * bars.mid


def main():
    per_signal_rows = []
    per_trade_rows = []

    for symbol in SYMBOLS:
        for day in DAYS:
            bars, tob = get_bars_and_tob(symbol, day, download_l2_day, bar_ms=500)
            if bars.empty or tob.empty:
                continue
            bars = bars.copy()
            bars['vol_unit'] = compute_vol_unit(bars)

            tob_idx_i8 = tob.index.asi8
            tob_bid = tob.best_bid.to_numpy()
            tob_ask = tob.best_ask.to_numpy()
            tob_mid = tob.mid.to_numpy()

            raw_signals = generate_l2_signals(bars, symbol, MECHANISM)
            exec_signals = build_execution_signals(bars, symbol, MECHANISM)
            exec_by_ts = {s['timestamp']: s for s in exec_signals}

            # ---- run MICRO-SIM exactly as before: no parameter changes ----
            base_cfg = MicroSimConfig(fee_bps=5.0, slippage_bps=2.0)
            result = execute_l2_single_symbol(bars, exec_signals, base_cfg, initial_capital=250)
            trades_by_setup = {t['setup_id']: t for t in result['trades']}
            diag = result['summary']['diagnostics']

            n_candidates = len(raw_signals)
            n_had_volunit = len(exec_signals)
            n_entries = diag['entries']

            for sig in raw_signals:
                ts = sig['decision_ts']
                side = sig['side']
                decision_i8 = ts.value

                entry0 = asof_row(tob_idx_i8, tob_bid, tob_ask, tob_mid, decision_i8)
                if entry0 is None:
                    continue
                real_bid0, real_ask0, mid_at_decision, _ = entry0
                real_fill_price = real_ask0 if side == 1 else real_bid0

                horizon_i8 = decision_i8 + HORIZON_5S_NS
                exit5 = asof_row(tob_idx_i8, tob_bid, tob_ask, tob_mid, horizon_i8)
                if exit5 is None:
                    continue
                _, _, mid_at_5s, _ = exit5

                # leg A: decision -> decision+5s (mid-to-mid)
                leg_a_bps = side * (mid_at_5s / mid_at_decision - 1.0) * 10_000
                # leg B: decision -> real fill (spread cost of getting in, 0ms)
                leg_b_bps = side * (real_fill_price / mid_at_decision - 1.0) * 10_000
                # leg C: real fill -> decision+5s (alpha remaining after paying spread)
                leg_c_bps = side * (mid_at_5s / real_fill_price - 1.0) * 10_000

                had_volunit = ts in exec_by_ts
                vol_unit = float(bars.vol_unit.loc[ts]) if had_volunit else np.nan
                risk_bps = (STOP_VOL_MULT * vol_unit / real_fill_price * 10_000) if had_volunit and np.isfinite(vol_unit) and vol_unit > 0 else np.nan
                leg_c_R = leg_c_bps / risk_bps if risk_bps and np.isfinite(risk_bps) and risk_bps > 0 else np.nan

                setup_id = None
                if had_volunit:
                    direction = 'long' if side == 1 else 'short'
                    setup_id = f'{MECHANISM}:v1:{symbol}:{direction}:{ts.isoformat()}'
                filled = setup_id is not None and setup_id in trades_by_setup

                per_signal_rows.append({
                    'symbol': symbol, 'day': day, 'decision_ts': ts, 'side': side,
                    'had_volunit': had_volunit, 'filled': filled,
                    'leg_a_bps': leg_a_bps, 'leg_b_bps': leg_b_bps, 'leg_c_bps': leg_c_bps,
                    'leg_c_R': leg_c_R, 'risk_bps': risk_bps,
                })

                if filled:
                    t = trades_by_setup[setup_id]
                    fill_ts_i8 = pd.Timestamp(t['opened_at']).value
                    exit_ts_i8 = pd.Timestamp(t['closed_at']).value
                    path_bid, path_ask = window_path(tob_idx_i8, tob_bid, tob_ask, fill_ts_i8, exit_ts_i8)
                    exit_side_path = path_bid if side == 1 else path_ask
                    if len(exit_side_path) > 0:
                        signed_path_bps = side * (exit_side_path / real_fill_price - 1.0) * 10_000
                        mfe_bps = float(signed_path_bps.max())
                        mae_bps = float(signed_path_bps.min())
                        signed_path_R = signed_path_bps / risk_bps if risk_bps and np.isfinite(risk_bps) and risk_bps > 0 else np.array([np.nan])
                        reach = {f'reach_{r}R': bool(np.nanmax(signed_path_R) >= r) for r in R_CHECKPOINTS}
                    else:
                        mfe_bps = mae_bps = np.nan
                        reach = {f'reach_{r}R': False for r in R_CHECKPOINTS}

                    hold_s = (pd.Timestamp(t['closed_at']) - pd.Timestamp(t['opened_at'])).total_seconds()
                    per_trade_rows.append({
                        'symbol': symbol, 'day': day, 'side': side,
                        'gross_pnl': t['gross_pnl'], 'fees': t['fees'], 'pnl': t['pnl'],
                        'r_multiple': t['r_multiple'], 'reason': t['reason'], 'hold_s': hold_s,
                        'leg_c_R': leg_c_R, 'mfe_bps': mfe_bps, 'mae_bps': mae_bps, **reach,
                    })

    sig_df = pd.DataFrame(per_signal_rows)
    trade_df = pd.DataFrame(per_trade_rows)

    def block(label, df_sig, df_trd):
        print(f'\n{"="*100}\n{label}\n{"="*100}')
        n_sig = len(df_sig)
        n_vu = df_sig.had_volunit.sum()
        n_fill = df_sig.filled.sum()
        print(f'signals={n_sig}  had_vol_unit(order attempts)={n_vu}  fills={n_fill}  '
              f'fill_probability={n_fill/n_sig*100:.1f}% of signals, {n_fill/n_vu*100:.1f}% of attempts')
        print('decision->order latency: 0ms (MICRO-SIM fills within the same 500ms bar as the signal)')
        print('decision->fill latency: 0ms modeled; real-fill leg B computed at TOB asof(decision_ts+0ms)')

        gross_a = df_sig.leg_a_bps.mean()
        gross_b = df_sig.leg_b_bps.mean()
        gross_c = df_sig.leg_c_bps.mean()
        print(f'\nLeg A (decision->+5s, mid):        mean={gross_a:+.4f} bps  (all {n_sig} signals)')
        print(f'Leg B (decision->real fill, 0ms):  mean={gross_b:+.4f} bps  (= real spread cost paid to enter)')
        print(f'Leg C (real fill->+5s, mid):       mean={gross_c:+.4f} bps  (= gross alpha surviving real entry cost)')

        c_filled = df_sig[df_sig.filled].leg_c_bps
        c_R_filled = df_sig[df_sig.filled].leg_c_R.dropna()
        print(f'Leg C on FILLED signals only:      mean={c_filled.mean():+.4f} bps  n={len(c_filled)}')
        print(f'Gross expectancy from real fill (R, filled only): mean={c_R_filled.mean():+.4f}R  '
              f'median={c_R_filled.median():+.4f}R  n={len(c_R_filled)}')

        if len(df_trd) == 0:
            print('\nNo filled trades in this subset.')
            return
        gains = df_trd.pnl[df_trd.pnl > 0].sum()
        losses = -df_trd.pnl[df_trd.pnl < 0].sum()
        gross_gains = df_trd.gross_pnl[df_trd.gross_pnl > 0].sum()
        gross_losses = -df_trd.gross_pnl[df_trd.gross_pnl < 0].sum()
        n = len(df_trd)
        wr = (df_trd.pnl > 0).mean() * 100
        avg_win = df_trd.pnl[df_trd.pnl > 0].mean() if (df_trd.pnl > 0).any() else 0.0
        avg_loss = df_trd.pnl[df_trd.pnl < 0].mean() if (df_trd.pnl < 0).any() else 0.0
        n_days = df_trd.day.nunique()
        print(f'\n-- MICRO-SIM realized trades (leg D: fill -> actual dynamic exit) --')
        print(f'trades={n}  win_rate={wr:.1f}%  median_hold={df_trd.hold_s.median():.1f}s')
        print(f'gross_PF={gross_gains/gross_losses if gross_losses else float("nan"):.3f}  '
              f'net_PF={gains/losses if losses else float("nan"):.3f}')
        # initial_risk_usd = pnl / r_multiple (by construction in micro_sim.py); reuse it so
        # gross_R uses the exact same risk unit as the reported net_R, not a re-derived one.
        gross_r = (df_trd.gross_pnl / (df_trd.pnl / df_trd.r_multiple).abs()).replace([np.inf, -np.inf], np.nan)
        print(f'gross_expectancy_R={gross_r.mean():+.4f}R   net_expectancy_R={df_trd.r_multiple.mean():+.4f}R')
        print(f'gross_$/trade={df_trd.gross_pnl.mean():+.4f}   net_$/trade={df_trd.pnl.mean():+.4f}')
        print(f'avg_win=${avg_win:.4f}   avg_loss=${avg_loss:.4f}')
        print(f'MFE(from fill) mean={df_trd.mfe_bps.mean():+.3f}bps   MAE(from fill) mean={df_trd.mae_bps.mean():+.3f}bps')
        for r in R_CHECKPOINTS:
            print(f'% trades reaching +{r}R before stop: {df_trd[f"reach_{r}R"].mean()*100:.1f}%')
        print(f'total_net_pnl=${df_trd.pnl.sum():.2f}   over {n_days} days -> ${df_trd.pnl.sum()/n_days:.4f}/day')

        print('\nper symbol (net $):')
        for s, g in df_trd.groupby('symbol'):
            print(f'  {s}: trades={len(g)} net=${g.pnl.sum():.2f} expectancy_R={g.r_multiple.mean():+.4f}')
        print('per day (net $):')
        for d, g in df_trd.groupby('day'):
            print(f'  {d}: trades={len(g)} net=${g.pnl.sum():.2f}')

    block('PRIMARY: ALL (BTC+ETH+SOL) -- frozen universe', sig_df, trade_df)
    block('diagnostic: BTC only', sig_df[sig_df.symbol == 'BTCUSDT'], trade_df[trade_df.symbol == 'BTCUSDT'])
    block('diagnostic: ETH only', sig_df[sig_df.symbol == 'ETHUSDT'], trade_df[trade_df.symbol == 'ETHUSDT'])
    block('diagnostic: SOL only', sig_df[sig_df.symbol == 'SOLUSDT'], trade_df[trade_df.symbol == 'SOLUSDT'])
    block('diagnostic: BTC+ETH only (NOT primary -- reported per explicit instruction, not a substitute result)',
          sig_df[sig_df.symbol != 'SOLUSDT'], trade_df[trade_df.symbol != 'SOLUSDT'])

    sig_df.to_csv('/tmp/sentinel-tick-cache/l2a_audit_signals.csv', index=False)
    trade_df.to_csv('/tmp/sentinel-tick-cache/l2a_audit_trades.csv', index=False)


if __name__ == '__main__':
    main()
