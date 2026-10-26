"""Stage 1 OOS test for L2A-5S and L2B-REV-5S, per
docs/research/l2_oos_stage1_protocol.md. Frozen dates, frozen signal
definitions, frozen fixed-5s-exit execution model, no re-tuning after
seeing results. Reuses get_bars_and_tob (retry/backoff + parsed-output
caching already built for L2-EDGE) so a rerun never re-hits Tardis.dev
for a symbol-day it already has.
"""
import numpy as np
import pandas as pd

from .download_l2_edge import get_bars_and_tob
from .download_l2_hist import download_l2_day
from .l2_fixed_exit_sim import FixedExitConfig, run_fixed_exit_sim
from .l2_signals import SYMBOLS, generate_signals

STAGE1_DAYS = ['2026-02-01', '2026-03-01', '2026-04-01', '2026-05-01', '2026-06-01', '2026-07-01']
VOL_WINDOW = 120
LATENCIES_MS = (250, 500, 1000)  # 250 = primary
RNG = np.random.default_rng(7)
N_BOOT = 2000


def compute_vol_unit(bars):
    ret_60s = np.log(bars.mid).diff(120)
    return ret_60s.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std() * bars.mid


def block_bootstrap_ci(day_pnls, n_boot=N_BOOT):
    """day_pnls: {day: np.array of per-trade pnl (or bps) for that day}.
    Resamples WHOLE DAYS -- with only 6 discovery/Stage-1 days this CI is
    necessarily wide; reported honestly, not oversold as strong evidence."""
    days = list(day_pnls.keys())
    means = []
    for _ in range(n_boot):
        sampled = RNG.choice(days, size=len(days), replace=True)
        pooled = np.concatenate([day_pnls[d] for d in sampled])
        means.append(pooled.mean())
    means = np.array(means)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main():
    all_bars_tob = {}
    for symbol in SYMBOLS:
        for day in STAGE1_DAYS:
            print(f'downloading/parsing {symbol} {day}...', flush=True)
            bars, tob = get_bars_and_tob(symbol, day, download_l2_day, bar_ms=500)
            if bars.empty or tob.empty:
                continue
            bars = bars.copy()
            bars['vol_unit'] = compute_vol_unit(bars)
            all_bars_tob[(symbol, day)] = (bars, tob)

    for mechanism in ('L2B-REV', 'L2A'):
        label = 'PRIMARY: L2B-REV-5S' if mechanism == 'L2B-REV' else 'SECONDARY: L2A-5S'
        print(f'\n{"="*100}\n{label}\n{"="*100}')

        for lat_ms in LATENCIES_MS:
            tag = 'PRIMARY 250ms' if lat_ms == 250 else f'sensitivity {lat_ms}ms'
            print(f'\n---- latency={lat_ms}ms ({tag}) ----')
            for cost_tag, cfg_kwargs in (
                ('BASE', dict(fee_bps=5.0, extra_slippage_bps=0.0)),
                ('STRESS', dict(fee_bps=8.0, extra_slippage_bps=3.0)),
            ):
                cfg = FixedExitConfig(latency_ms=lat_ms, **cfg_kwargs)
                all_trades = []
                per_symbol_net = {}
                day_pnl_bps = {d: [] for d in STAGE1_DAYS}
                total_signals = total_fills = 0

                for symbol in SYMBOLS:
                    sym_net = 0.0
                    for day in STAGE1_DAYS:
                        key = (symbol, day)
                        if key not in all_bars_tob:
                            continue
                        bars, tob = all_bars_tob[key]
                        raw_signals = generate_signals(bars, symbol, mechanism)
                        signals = []
                        for sig in raw_signals:
                            vu = bars.vol_unit.loc[sig['decision_ts']] if sig['decision_ts'] in bars.index else np.nan
                            signals.append({**sig, 'vol_unit': float(vu) if np.isfinite(vu) else None})

                        result = run_fixed_exit_sim(bars, tob, signals, cfg, initial_capital=250.0)
                        total_signals += result['diagnostics']['signals']
                        total_fills += result['diagnostics']['fills']
                        sym_net += result['summary']['net_pnl']
                        for t in result['trades']:
                            t['symbol'], t['day'] = symbol, day
                            all_trades.append(t)
                            day_pnl_bps[day].append(t['pnl'] / t['risk_usd'])  # r_multiple, used for bootstrap CI
                    per_symbol_net[symbol] = sym_net

                if not all_trades:
                    print(f'  {cost_tag}: no trades')
                    continue
                tdf = pd.DataFrame(all_trades)
                n = len(tdf)
                n_days = tdf.day.nunique()
                wr = (tdf.pnl > 0).mean() * 100
                gains = tdf.pnl[tdf.pnl > 0].sum()
                losses = -tdf.pnl[tdf.pnl < 0].sum()
                gross_gains = tdf.gross_pnl[tdf.gross_pnl > 0].sum()
                gross_losses = -tdf.gross_pnl[tdf.gross_pnl < 0].sum()
                gross_bps_mean = tdf.gross_bps.mean()
                net_bps_mean = tdf.net_bps.mean()
                net_r = tdf.r_multiple.mean()
                gross_r = tdf.gross_r.mean()

                equity_by_symbol = {}
                max_dd_pct = 0.0
                for symbol in SYMBOLS:
                    sub = tdf[tdf.symbol == symbol].sort_values('decision_ts')
                    eq = 250.0 + sub.pnl.cumsum()
                    eq = pd.concat([pd.Series([250.0]), eq])
                    running_max = eq.cummax()
                    dd = ((running_max - eq) / running_max * 100)
                    max_dd_pct = max(max_dd_pct, float(dd.max()) if len(dd) else 0.0)

                day_r = {d: np.array(v) for d, v in day_pnl_bps.items() if v}
                ci_lo, ci_hi = block_bootstrap_ci(day_r) if len(day_r) >= 2 else (float('nan'), float('nan'))

                print(f'  {cost_tag}: signals={total_signals} fills={total_fills} '
                      f'fill_rate={total_fills/total_signals*100:.1f}% trades/day={n/n_days:.2f}')
                print(f'    gross_bps/trade={gross_bps_mean:+.4f}  net_bps/trade={net_bps_mean:+.4f}')
                print(f'    gross_R/trade={gross_r:+.4f}  net_R/trade={net_r:+.4f}  '
                      f'gross_PF={gross_gains/gross_losses if gross_losses else float("nan"):.3f}  '
                      f'net_PF={gains/losses if losses else float("nan"):.3f}')
                print(f'    win_rate={wr:.1f}%  avg_win=${tdf.pnl[tdf.pnl>0].mean() if (tdf.pnl>0).any() else 0:.4f}  '
                      f'avg_loss=${tdf.pnl[tdf.pnl<0].mean() if (tdf.pnl<0).any() else 0:.4f}')
                print(f'    total_net_pnl(sum of independent $250 books)=${tdf.pnl.sum():.2f}  '
                      f'net_$/day={tdf.pnl.sum()/n_days:.4f}  max_DD%={max_dd_pct:.2f}')
                print(f'    bootstrap 95% CI mean net_R/trade (block-by-day, n_days={len(day_r)}): '
                      f'[{ci_lo:.4f}, {ci_hi:.4f}]  {"EXCLUDES 0" if ci_lo>0 or ci_hi<0 else "INCLUDES 0"}')
                print(f'    per symbol net $: {per_symbol_net}')
                if lat_ms == 250:
                    print('    per day net $:')
                    for d, g in tdf.groupby('day'):
                        print(f'      {d}: trades={len(g)} net=${g.pnl.sum():.2f}')


if __name__ == '__main__':
    main()
