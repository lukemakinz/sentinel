"""L2-HIST ETAP 2-4 combined: three frozen mechanisms on real OKX L2
order-book data (500ms bars), each taken straight to a costed $250
backtest. Data: 6 free Tardis.dev sample days (first of each month,
2025-08-01 .. 2026-01-01), BTC/ETH/SOL -- not continuous, disclosed
limitation (no true dev/validation/holdout split possible on this free
sample; every day here is effectively "development").

Three frozen mechanisms (thresholds: z>=2.0, consistent with this
project's convention elsewhere -- not swept):
  L2-A pressure continuation: imbalance5 z-extreme AND ofi z-extreme,
       same sign -> trade WITH the pressure.
  L2-B absorption reversal: one side's top depth collapses sharply
       (z-extreme) while price (mid, trailing 1.5s) barely moved ->
       fade AGAINST the consuming side (absorption, not follow-through).
  L2-C liquidity vacuum: one side's 5-level depth collapses sharply
       (z-extreme) via thinning (not matched by the other side moving)
       -> trade TOWARD the thin side (path of least resistance).

Execution: standard bounce-style ($250, $0.50 risk, ATR-based stop from
1-minute Binance bars for that same day, base+stress costs).
"""
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import talib

from l1_filter.scalp_strategy import ScalpConfig
from .cluster_scalp_simulator import execute_cluster
from .download_l2_hist import build_feature_bars, download_l2_day
from .scalp_data import load_archives

SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
DAYS = ['2025-08-01', '2025-09-01', '2025-10-01', '2025-11-01', '2025-12-01', '2026-01-01']
ZSCORE_WINDOW = 120  # bars (60s at 500ms)
ZSCORE_EXTREME = 2.0
STOP_ATR_MULT = 1.0
BINANCE_CACHE = '/tmp/sentinel-scalp-cache'


def bounce_execution(name):
    # target_r raised from an initial 3.0 to 8.0 (matching S20/LQX2's
    # already-precedented "patient" value) after diagnosing that 3.0
    # structurally could never clear this project's own 3x reward/cost
    # filter at these symbols' typical 1-minute ATR/price ratio (reward
    # capped by a small ATR-based risk vs. cost scaling with price) --
    # a parameter-design bug caught in review, not a tuning-for-result.
    return ScalpConfig(
        name=name, minutes=5, target_r=8.0, partial_r=1.5, partial_fraction=0.0,
        trailing=True, trail_atr=2.5, max_hold_minutes=30, risk_fraction=0.0020,
        max_notional_equity=0.50, daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
        min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
        margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
        fixed_margin_usd=25.0, fixed_risk_usd=0.50,
    )


def zscore(series, window=ZSCORE_WINDOW):
    mean = series.shift(1).rolling(window, min_periods=window).mean()
    std = series.shift(1).rolling(window, min_periods=window).std()
    return (series - mean) / std.where(std > 0)


def compute_bars_with_features(symbol, day):
    path = download_l2_day(symbol, day)
    bars = build_feature_bars(path, bar_ms=500)
    Path(path).unlink(missing_ok=True)  # disk is small (~9.7GB); each raw L2 day is ~0.9-2GB
    if bars.empty:
        return None
    bars['mid_ret_3bars'] = bars.mid.pct_change(3) * 10_000
    bars['depth1_ask_chg'] = bars.depth1_ask.diff()
    bars['depth1_bid_chg'] = bars.depth1_bid.diff()
    bars['depth5_ask_chg'] = bars.depth5_ask.diff()
    bars['depth5_bid_chg'] = bars.depth5_bid.diff()
    bars['z_imbalance5'] = zscore(bars.imbalance5)
    bars['z_ofi'] = zscore(bars.ofi)
    bars['z_depth1_ask_chg'] = zscore(bars.depth1_ask_chg)
    bars['z_depth1_bid_chg'] = zscore(bars.depth1_bid_chg)
    bars['z_depth5_ask_chg'] = zscore(bars.depth5_ask_chg)
    bars['z_depth5_bid_chg'] = zscore(bars.depth5_bid_chg)
    return bars


def generate_signals(bars, symbol, mechanism, atr_series, binance_close_series):
    """NOTE: execute_cluster fills at Binance's own row.open, ignoring the
    signal's 'reference' field, and computes risk as (Binance_entry -
    signal['stop']). The OKX order book (mid/depth/imbalance) is used
    ONLY to decide WHEN and which DIRECTION to trade -- reference/stop
    must be anchored to Binance's own price at that instant, not OKX's,
    or risk becomes cross-exchange-gap noise instead of an ATR stop
    (caught in review before any result was reported)."""
    records = []
    n = len(bars)
    mid = bars.mid.to_numpy()
    z_imb5 = bars.z_imbalance5.to_numpy()
    z_ofi = bars.z_ofi.to_numpy()
    mid_ret3 = bars.mid_ret_3bars.to_numpy()
    z_d1a = bars.z_depth1_ask_chg.to_numpy()
    z_d1b = bars.z_depth1_bid_chg.to_numpy()
    z_d5a = bars.z_depth5_ask_chg.to_numpy()
    z_d5b = bars.z_depth5_bid_chg.to_numpy()
    timestamps = bars.index

    prev_fired = False
    for i in range(n):
        fired, side = False, 0
        if mechanism == 'L2A':
            if np.isfinite(z_imb5[i]) and np.isfinite(z_ofi[i]):
                if z_imb5[i] >= ZSCORE_EXTREME and z_ofi[i] >= ZSCORE_EXTREME:
                    fired, side = True, 1
                elif z_imb5[i] <= -ZSCORE_EXTREME and z_ofi[i] <= -ZSCORE_EXTREME:
                    fired, side = True, -1
        elif mechanism == 'L2B':
            if np.isfinite(z_d1a[i]) and np.isfinite(mid_ret3[i]) and abs(mid_ret3[i]) < 1.0:
                if z_d1a[i] <= -ZSCORE_EXTREME:  # ask top depth collapsed (consumed) but price didn't follow
                    fired, side = True, -1  # fade: expect reversal down (buying absorbed)
                elif z_d1b[i] <= -ZSCORE_EXTREME:
                    fired, side = True, 1  # fade: expect reversal up (selling absorbed)
        elif mechanism == 'L2C':
            if np.isfinite(z_d5a[i]) and z_d5a[i] <= -ZSCORE_EXTREME:
                fired, side = True, 1  # ask side vacuum -> path of least resistance up
            elif np.isfinite(z_d5b[i]) and z_d5b[i] <= -ZSCORE_EXTREME:
                fired, side = True, -1

        if not fired or prev_fired:
            prev_fired = fired
            continue
        prev_fired = True

        ts = timestamps[i]
        atr = atr_series.asof(ts)
        binance_price = binance_close_series.asof(ts)
        if (atr is None or not np.isfinite(atr) or atr <= 0
                or binance_price is None or not np.isfinite(binance_price)):
            continue
        reference = binance_price  # anchored to Binance, not OKX mid -- see note above
        stop = reference - side * STOP_ATR_MULT * atr
        risk = side * (reference - stop)
        if risk <= 0:
            continue
        direction = 'long' if side == 1 else 'short'
        # execute_cluster's replay loop walks Binance's 1-MINUTE index and
        # looks signals up by exact timestamp match -- a sub-minute
        # timestamp is invisible to it (caught via diagnostics showing
        # 'signals': 0 despite thousands of real candidates). Snap to the
        # next whole minute as a disclosed workaround: this delays entry
        # by up to 59s versus the true 500ms trigger, a real cost to a
        # microstructure thesis, not a free fix. A proper fix would give
        # cluster_scalp_simulator a sub-minute replay grid -- out of
        # scope for this discovery pass.
        ts_exec = ts.ceil('1min')
        records.append({
            'timestamp': ts_exec, 'side': side, 'reference': float(reference),
            'stop': float(stop), 'min_stop_atr': 0.3, 'max_stop_atr': 3.0,
            'atr': float(atr), 'score': 6, 'setup': f'{mechanism}_{symbol}',
            'setup_id': f'{mechanism}:v1:{symbol}:{direction}:{ts.isoformat()}',
        })
    records.sort(key=lambda r: r['timestamp'])
    counts = Counter(r['timestamp'] for r in records)
    return [r for r in records if counts[r['timestamp']] == 1]


def main():
    all_bars = {}
    for symbol in SYMBOLS:
        for day in DAYS:
            print(f'downloading/parsing {symbol} {day}...', flush=True)
            bars = compute_bars_with_features(symbol, day)
            if bars is not None:
                all_bars[(symbol, day)] = bars

    for mechanism in ('L2A', 'L2B', 'L2C'):
        print(f'\n{"="*90}\n{mechanism}\n{"="*90}')
        markets, raw = {}, {}
        for symbol in SYMBOLS:
            symbol_signals = []
            day_minutes = []
            for day in DAYS:
                key = (symbol, day)
                if key not in all_bars:
                    continue
                bars = all_bars[key]
                minutes, funding, _ = load_archives(symbol, day, (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime('%Y-%m-%d'), BINANCE_CACHE)
                day_minutes.append((minutes, funding))
                resampled_1m = minutes.resample('1min').agg({'high': 'max', 'low': 'min', 'close': 'last'})
                atr_1m = pd.Series(
                    talib.ATR(resampled_1m.high.to_numpy(), resampled_1m.low.to_numpy(),
                              resampled_1m.close.to_numpy(), timeperiod=14),
                    index=resampled_1m.index)
                symbol_signals.extend(generate_signals(bars, symbol, mechanism, atr_1m, resampled_1m.close))
            if day_minutes:
                all_minutes = pd.concat([m for m, f in day_minutes])
                all_funding = pd.concat([f for m, f in day_minutes])
                markets[symbol] = (all_minutes, all_funding)
                raw[symbol] = symbol_signals
                print(f'  {symbol}: {len(symbol_signals)} candidates')

        total = sum(len(v) for v in raw.values())
        print(f'  Total candidates: {total} ({total/len(DAYS):.2f}/day pooled)')
        if total == 0 or not markets:
            print('  No candidates -- skipping backtest.')
            continue

        execution = bounce_execution(mechanism)
        base_results, stress_results = [], []
        for day in DAYS:
            start, end = day, (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            day_markets = {s: markets[s] for s in markets}
            try:
                base = execute_cluster(day_markets, raw, execution, start, end,
                                        initial_capital=250, symbol_priority=SYMBOLS)
                stress_exec = replace(execution, maker_fee_bps=5.0, fee_bps=8.0,
                                      slippage_bps=5.0, limit_penetration_bps=5.0)
                stress = execute_cluster(day_markets, raw, stress_exec, start, end,
                                          initial_capital=250, symbol_priority=SYMBOLS)
                base_results.append(base['summary'])
                stress_results.append(stress['summary'])
            except Exception as exc:
                print(f'  {day}: backtest error ({str(exc)[:100]})')

        total_trades = sum(r['trades'] for r in base_results)
        total_net_base = sum(r['net_pnl'] for r in base_results)
        total_net_stress = sum(r['net_pnl'] for r in stress_results)
        total_wins = sum(r['wins'] for r in base_results)
        print(f'\n  {mechanism} FINAL $250 RESULT across {len(DAYS)} days:')
        print(f'    trades={total_trades}  win_rate={total_wins/total_trades*100:.1f}%' if total_trades else '    trades=0')
        print(f'    net_pnl base=${total_net_base:.2f}  net_pnl stress=${total_net_stress:.2f}')


if __name__ == '__main__':
    main()
