"""DISCOVERY / SMOKE-TEST -- not a frozen protocol. New edge family:
1-5m intraday momentum/breakout, the only genuinely untested direction
of the three proposed after S46 was rejected (liquidation/forced-flow
momentum = S38/S39, already tested and rejected; cross-sectional
momentum = XSM-28, already tested and rejected).

Regime for this phase, as agreed:
  - development window ONLY -- validation and retrospective_evaluation
    stay completely unseen.
  - exactly 4 pre-defined, mechanically distinct hypotheses -- no
    parameter grid, no 27 combinations.
  - base + stress costs only (severe deferred to the freeze stage).
  - judged on expectancy_R, PF, trade count, max DD, per-symbol
    stability -- NOT on dollar PnL or $25/day (explicitly deferred).
  - if one variant looks genuinely worth pursuing, it gets a real
    protocol.json (hash, sizing, base/stress/severe, GO/NO-GO gate)
    BEFORE validation is ever touched. Nothing here is a promotion.

Four hypotheses:
  D1 opening_range_breakout -- 5m close breaks the prior rolling 1h
     (12x5m) high/low, with a volume confirmation.
  D2 vwap_reclaim -- 5m close crosses back above/below the session
     (daily, UTC-anchored) VWAP after 2+ bars on the other side.
  D3 micro_pullback -- 1m: a 3-bar same-direction impulse (range >=1.5x
     ATR(1m)) followed by exactly one opposite-direction pullback bar
     that does not erase the impulse's origin; enter on continuation.
  D4 volume_spike_momentum -- 5m candle with range >=2x ATR and volume
     >=3x its 20-bar average; enter WITH the candle's direction
     (momentum, not fade -- the mirror-image test of S38/S39, but pure
     price/volume, no OI gating, and on a much faster timeframe).

Execution for all four is a fast scalp shape (not S20's patient
runner): partial at 1R -> breakeven, chandelier trail at 1x ATR,
hard cap at 3R, max hold 60 minutes -- a priori, identical across all
four variants so any difference is attributable to entry logic only.
"""
from collections import Counter

import numpy as np
import pandas as pd
import talib

from l1_filter.scalp_strategy import ScalpConfig, resample_closed
from .cluster_scalp_simulator import execute_cluster
from .scalp_data import load_archives

TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
WARMUP, END = '2025-04-01', '2026-02-01'
DEV_START, DEV_END = '2025-08-01', '2026-02-01'


def fast_scalp_execution(name: str) -> ScalpConfig:
    return ScalpConfig(
        name=name, minutes=5, target_r=3.0, partial_r=1.0,
        partial_fraction=0.0, trailing=True, trail_atr=1.0,
        max_hold_minutes=60, risk_fraction=0.0020, max_notional_equity=0.50,
        daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
        min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
        margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
        fixed_margin_usd=25.0, fixed_risk_usd=0.50,
    )


def _emit(records, timestamp, side, reference, stop, atr, symbol, tag):
    risk = side * (reference - stop)
    if risk <= 0:
        return
    direction = 'long' if side == 1 else 'short'
    records.append({
        'timestamp': timestamp, 'side': side, 'reference': float(reference),
        'stop': float(stop), 'min_stop_atr': 0.5, 'max_stop_atr': 4.0,
        'atr': float(atr), 'score': 6, 'setup': f'{tag}_{symbol}',
        'setup_id': f'{tag}:v1:{symbol}:{direction}:{timestamp.isoformat()}',
    })


def _finalize(records):
    records.sort(key=lambda r: r['timestamp'])
    counts = Counter(r['timestamp'] for r in records)
    return [r for r in records if counts[r['timestamp']] == 1]


# ---------------------------------------------------------------------
# D1: opening-range / rolling short-range breakout (5m)
# ---------------------------------------------------------------------
def d1_opening_range_breakout(minutes, symbol):
    bars = resample_closed(minutes, 5)
    high, low, close = bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy()
    atr = talib.ATR(high, low, close, timeperiod=14)
    range_high = bars.high.shift(1).rolling(12, min_periods=12).max().to_numpy()
    range_low = bars.low.shift(1).rolling(12, min_periods=12).min().to_numpy()
    vol_base = bars.volume.shift(1).rolling(20, min_periods=20).mean().to_numpy()
    volume = bars.volume.to_numpy()

    records = []
    for i in range(len(bars)):
        if not (np.isfinite(atr[i]) and np.isfinite(range_high[i]) and np.isfinite(vol_base[i])):
            continue
        if volume[i] < 1.2 * vol_base[i]:
            continue
        if close[i] > range_high[i]:
            stop = range_high[i] - 0.15 * atr[i]
            _emit(records, bars.index[i], 1, close[i], stop, atr[i], symbol, 'D1_orb')
        elif close[i] < range_low[i]:
            stop = range_low[i] + 0.15 * atr[i]
            _emit(records, bars.index[i], -1, close[i], stop, atr[i], symbol, 'D1_orb')
    return _finalize(records)


# ---------------------------------------------------------------------
# D2: VWAP reclaim momentum (5m, daily UTC-anchored VWAP)
# ---------------------------------------------------------------------
def d2_vwap_reclaim(minutes, symbol):
    bars = resample_closed(minutes, 5)
    high, low, close = bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy()
    atr = talib.ATR(high, low, close, timeperiod=14)

    typical = (bars.high + bars.low + bars.close) / 3.0
    day = bars.index.tz_convert('UTC').normalize()
    pv = (typical * bars.volume).groupby(day).cumsum()
    vv = bars.volume.groupby(day).cumsum()
    vwap = (pv / vv).to_numpy()

    above = close > vwap
    vol_base = bars.volume.shift(1).rolling(20, min_periods=20).mean().to_numpy()
    volume = bars.volume.to_numpy()

    records = []
    for i in range(2, len(bars)):
        if not (np.isfinite(atr[i]) and np.isfinite(vwap[i]) and np.isfinite(vol_base[i])):
            continue
        if volume[i] < 1.2 * vol_base[i]:
            continue
        was_below = not above[i - 1] and not above[i - 2]
        was_above = above[i - 1] and above[i - 2]
        if was_below and above[i]:
            stop = vwap[i] - 0.15 * atr[i]
            _emit(records, bars.index[i], 1, close[i], stop, atr[i], symbol, 'D2_vwap')
        elif was_above and not above[i]:
            stop = vwap[i] + 0.15 * atr[i]
            _emit(records, bars.index[i], -1, close[i], stop, atr[i], symbol, 'D2_vwap')
    return _finalize(records)


# ---------------------------------------------------------------------
# D3: micro-pullback continuation (1m impulse + 1-bar pullback)
# ---------------------------------------------------------------------
def d3_micro_pullback(minutes, symbol):
    bars = minutes
    open_, high, low, close = (bars.open.to_numpy(), bars.high.to_numpy(),
                               bars.low.to_numpy(), bars.close.to_numpy())
    atr = talib.ATR(high, low, close, timeperiod=14)
    bullish = close > open_
    bearish = close < open_

    records = []
    n = len(bars)
    for i in range(3, n - 1):
        if not np.isfinite(atr[i]):
            continue
        impulse_up = bullish[i - 3] and bullish[i - 2] and bullish[i - 1]
        impulse_down = bearish[i - 3] and bearish[i - 2] and bearish[i - 1]
        impulse_range = high[i - 1] - low[i - 3] if impulse_up else (high[i - 3] - low[i - 1] if impulse_down else 0)
        if impulse_up and impulse_range >= 1.5 * atr[i] and bearish[i]:
            impulse_low = low[i - 3]
            if low[i] > impulse_low:  # pullback did not erase the impulse's origin
                entry_i = i + 1
                stop = low[i] - 0.15 * atr[i]
                _emit(records, bars.index[entry_i], 1, close[entry_i], stop, atr[i], symbol, 'D3_pullback')
        elif impulse_down and impulse_range >= 1.5 * atr[i] and bullish[i]:
            impulse_high = high[i - 3]
            if high[i] < impulse_high:
                entry_i = i + 1
                stop = high[i] + 0.15 * atr[i]
                _emit(records, bars.index[entry_i], -1, close[entry_i], stop, atr[i], symbol, 'D3_pullback')
    return _finalize(records)


# ---------------------------------------------------------------------
# D4: volume-spike momentum ignition (5m, pure price/volume, no OI)
# ---------------------------------------------------------------------
def d4_volume_spike_momentum(minutes, symbol):
    bars = resample_closed(minutes, 5)
    open_, high, low, close = (bars.open.to_numpy(), bars.high.to_numpy(),
                               bars.low.to_numpy(), bars.close.to_numpy())
    atr = talib.ATR(high, low, close, timeperiod=14)
    vol_base = bars.volume.shift(1).rolling(20, min_periods=20).mean().to_numpy()
    volume = bars.volume.to_numpy()
    bar_range = high - low

    records = []
    for i in range(len(bars)):
        if not (np.isfinite(atr[i]) and np.isfinite(vol_base[i]) and atr[i] > 0):
            continue
        if bar_range[i] < 2.0 * atr[i] or volume[i] < 3.0 * vol_base[i]:
            continue
        side = 1 if close[i] > open_[i] else -1
        extreme = low[i] if side == 1 else high[i]
        stop = extreme - side * 0.15 * atr[i]
        _emit(records, bars.index[i], side, close[i], stop, atr[i], symbol, 'D4_volspike')
    return _finalize(records)


VARIANTS = {
    'D1_opening_range_breakout': d1_opening_range_breakout,
    'D2_vwap_reclaim': d2_vwap_reclaim,
    'D3_micro_pullback': d3_micro_pullback,
    'D4_volume_spike_momentum': d4_volume_spike_momentum,
}


def summarize(summary, trades):
    longs = [t for t in trades if t['side'] == 'LONG']
    shorts = [t for t in trades if t['side'] == 'SHORT']
    per_symbol = {s: row['net_pnl'] for s, row in summary['per_symbol'].items()}
    return {
        'trades': summary['trades'], 'PF': summary['profit_factor'],
        'expectancy_R': round(summary['mean_net_r'], 4),
        'net_pnl': round(summary['net_pnl'], 2), 'max_DD_pct': round(summary['max_drawdown_pct'], 3),
        'long_n': len(longs), 'short_n': len(shorts), 'per_symbol_net': per_symbol,
    }


def main():
    cache = '/tmp/sentinel-scalp-cache'
    minutes_by_symbol = {}
    for symbol in TRADED:
        m, funding, _ = load_archives(symbol, WARMUP, END, cache)
        minutes_by_symbol[symbol] = (m, funding)
        print(symbol, 'archives ready', flush=True)

    markets = {symbol: minutes_by_symbol[symbol] for symbol in TRADED}

    for variant_name, generator in VARIANTS.items():
        execution = fast_scalp_execution(variant_name)
        raw = {symbol: generator(minutes_by_symbol[symbol][0], symbol) for symbol in TRADED}
        raw_count = sum(len(v) for v in raw.values())

        base = execute_cluster(markets, raw, execution, DEV_START, DEV_END,
                                initial_capital=250, symbol_priority=TRADED)
        from dataclasses import replace
        stress_exec = replace(execution, maker_fee_bps=5.0, fee_bps=8.0,
                              slippage_bps=5.0, limit_penetration_bps=5.0)
        stress = execute_cluster(markets, raw, stress_exec, DEV_START, DEV_END,
                                  initial_capital=250, symbol_priority=TRADED)

        print(f'\n{"="*70}\n{variant_name}  (raw candidates: {raw_count})\n{"="*70}')
        print('  base  :', summarize(base['summary'], base['trades']))
        print('  stress:', summarize(stress['summary'], stress['trades']))


if __name__ == '__main__':
    main()
