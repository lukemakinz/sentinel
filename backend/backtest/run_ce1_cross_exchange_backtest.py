"""CE-1: cross-exchange dislocation, taken all the way to a costed $
backtest -- not left as a bps-only screen (per explicit instruction:
every candidate gets a real $250 execute_cluster result, win or lose).

Mechanism: Binance is the traded instrument. Bybit is the reference
"fair value". At each 1-minute bar, compute
    divergence_bps = (binance_close - bybit_close) / bybit_close * 10000
When |divergence_bps| clears an absolute threshold, bet on
CONVERGENCE: Binance trading rich vs Bybit -> short Binance; Binance
trading cheap vs Bybit -> long Binance.

Threshold pre-check (before freezing this at 15bps): a z-score approach
was tried first and rejected as a design choice, not tuned away after
seeing results -- median 60-minute rolling divergence std is only
~0.5-0.6bps for these three pairs, so a z>=2 threshold corresponds to
roughly 1bps of ACTUAL divergence, the same tiny-vs-cost magnitude class
M1/M3 already found and rejected. An absolute-bps threshold is the
economically correct design for this specific question (Binance vs
Bybit and OKX are tightly cross-arbitraged under normal conditions;
genuinely large, rare dislocations are what this mechanism is supposed
to catch, not statistically-unusual noise within an already-quiet hour).
15bps was chosen a priori as roughly this project's own base round-trip
cost (14bps) -- the natural "does the move even clear cost" test, not
swept or fit to any outcome. At this threshold: ~0.18-0.56 events/day
per symbol (BTC/ETH/SOL), ~1.1/day pooled -- genuinely rare, as expected
for tightly-arbitraged major pairs.

Execution reuses this project's standard bounce-style exit (same shape
as S38/LQX1: target_r=3, trail_atr=1.5, partial_r=1.0, ATR-based stop)
-- a disclosed simplification (a bespoke "wait for convergence" exit
was not built for this first pass; the standard ATR stop/target is used
instead, consistent with how every other entry-signal family in this
project was first tested).
"""
from collections import Counter
from dataclasses import replace

import numpy as np
import pandas as pd
import talib

from l1_filter.scalp_strategy import ScalpConfig, resample_closed
from .cluster_scalp_simulator import execute_cluster
from .download_bybit_klines import load_bybit_klines
from .scalp_data import load_archives

TRADED = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
WARMUP, END = '2025-04-01', '2026-02-01'
DEV_START, DEV_END = '2025-08-01', '2026-02-01'

DIVERGENCE_THRESHOLD_BPS = 15.0  # chosen a priori: roughly this project's base round-trip cost (14bps)
# NOTE: 1.0x ATR, not the 0.15x used elsewhere in this project as a small
# BUFFER beyond an existing structural level (an order block edge, a
# cascade extreme). CE-1 has no such structural level to buffer beyond --
# the stop distance here IS the whole risk distance, so it must be a real
# stop width, not a tiny buffer. Using 0.15x directly (a first-draft
# copy-paste from other modules, caught in code review before any full
# backtest was read) made every single trade stop out with r=-1.00 almost
# immediately on ordinary 1-minute noise, before any real convergence had
# a chance to happen -- a design bug, not a result to report.
STOP_ATR_MULT = 1.0


def bounce_execution(name):
    return ScalpConfig(
        name=name, minutes=5, target_r=3.0, partial_r=1.0, partial_fraction=0.0,
        trailing=True, trail_atr=1.5, max_hold_minutes=120, risk_fraction=0.0020,
        max_notional_equity=0.50, daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
        min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
        margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
        fixed_margin_usd=25.0, fixed_risk_usd=0.50,
    )


def build_divergence_signals(binance_minutes, bybit_minutes, symbol):
    aligned = binance_minutes[['open', 'high', 'low', 'close']].join(
        bybit_minutes[['close']].rename(columns={'close': 'bybit_close'}), how='inner')
    if len(aligned) < 30:
        return []

    divergence_bps = (aligned.close / aligned.bybit_close - 1.0) * 10_000

    atr = talib.ATR(aligned.high.to_numpy(), aligned.low.to_numpy(), aligned.close.to_numpy(), timeperiod=14)

    close = aligned.close.to_numpy()
    div = divergence_bps.to_numpy()
    records = []
    for i in range(1, len(aligned)):
        if not np.isfinite(div[i]) or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        # Fire once per dislocation EPISODE (the crossing), not once per
        # minute the divergence remains extreme -- otherwise one episode
        # spams many correlated candidates in a row, which then trips the
        # daily-loss halt on the first bad one and blocks the rest of the
        # day (a mechanical artifact, not a property of the strategy).
        was_extreme = abs(div[i - 1]) >= DIVERGENCE_THRESHOLD_BPS if np.isfinite(div[i - 1]) else False
        if was_extreme:
            continue
        if div[i] >= DIVERGENCE_THRESHOLD_BPS:
            side = -1  # Binance rich vs Bybit -> short, expect convergence down
        elif div[i] <= -DIVERGENCE_THRESHOLD_BPS:
            side = 1   # Binance cheap vs Bybit -> long, expect convergence up
        else:
            continue
        reference = close[i]
        stop = reference - side * STOP_ATR_MULT * atr[i]
        risk = side * (reference - stop)
        if risk <= 0:
            continue
        direction = 'long' if side == 1 else 'short'
        ts = aligned.index[i]
        records.append({
            'timestamp': ts, 'side': side, 'reference': float(reference),
            'stop': float(stop), 'min_stop_atr': 0.3, 'max_stop_atr': 3.0,
            'atr': float(atr[i]), 'score': 6, 'setup': f'CE1_{symbol}',
            'setup_id': f'CE1:v1:{symbol}:{direction}:{ts.isoformat()}',
        })
    records.sort(key=lambda r: r['timestamp'])
    counts = Counter(r['timestamp'] for r in records)
    return [r for r in records if counts[r['timestamp']] == 1]


def main():
    binance_cache = '/tmp/sentinel-scalp-cache'
    bybit_cache = '/tmp/sentinel-bybit-cache'

    markets, raw = {}, {}
    for symbol in TRADED:
        binance_minutes, funding, _ = load_archives(symbol, WARMUP, END, binance_cache)
        bybit_minutes = load_bybit_klines(symbol, WARMUP, END, bybit_cache)
        markets[symbol] = (binance_minutes, funding)
        raw[symbol] = build_divergence_signals(binance_minutes, bybit_minutes, symbol)
        print(symbol, 'CE-1 candidates:', len(raw[symbol]), flush=True)

    total = sum(len(v) for v in raw.values())
    dev_days = (pd.Timestamp(DEV_END) - pd.Timestamp(DEV_START)).days
    print(f'\nTotal candidates: {total} ({total/dev_days:.2f}/day pooled, 3 symbols)')

    execution = bounce_execution('CE1_dislocation')
    base = execute_cluster(markets, raw, execution, DEV_START, DEV_END,
                            initial_capital=250, symbol_priority=TRADED)
    stress_exec = replace(execution, maker_fee_bps=5.0, fee_bps=8.0,
                          slippage_bps=5.0, limit_penetration_bps=5.0)
    stress = execute_cluster(markets, raw, stress_exec, DEV_START, DEV_END,
                              initial_capital=250, symbol_priority=TRADED)

    def summarize(result):
        s = result['summary']
        trades = result['trades']
        longs = [t for t in trades if t['side'] == 'LONG']
        shorts = [t for t in trades if t['side'] == 'SHORT']
        return {
            'trades': s['trades'], 'PF': s['profit_factor'],
            'expectancy_R': round(s['mean_net_r'], 4) if s['trades'] else None,
            'net_pnl_usd': round(s['net_pnl'], 2), 'max_DD_pct': round(s['max_drawdown_pct'], 3),
            'long_n': len(longs), 'short_n': len(shorts), 'per_symbol': s['per_symbol'],
        }

    print('\n' + '=' * 78)
    print('CE-1 FULL $250 BACKTEST RESULT (development window)')
    print('=' * 78)
    print('BASE  :', summarize(base))
    print('STRESS:', summarize(stress))


if __name__ == '__main__':
    main()
