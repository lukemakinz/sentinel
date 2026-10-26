"""LQX-1 DISCOVERY -- not a frozen protocol. New edge source: forced-flow
event classification, using OI direction not as a trend filter (as in
S18-S46) but to classify WHY a price/volume spike happened, before
deciding whether to fade or ride it. This is the genuinely new idea
S38/S39 did not test: those detected price+volume spikes with NO OI
information at all, then tried fade vs continuation blindly. Here every
spike is first classified:
    liquidation-type: OI z-score strongly NEGATIVE during the spike
        (positions closing under duress, regardless of price direction)
    fresh-flow-type:  OI z-score strongly POSITIVE during the spike
        (new conviction capital entering, regardless of price direction)

Four pre-defined variants -- two hypotheses plus their own built-in
mechanism check (no parameter grid):
    LQX1  liquidation-type -> FADE          (main hypothesis)
    LQX2  fresh-flow-type  -> CONTINUATION  (main hypothesis)
    LQX3  liquidation-type -> CONTINUATION  (control: should underperform
                                             LQX1 if the classification
                                             actually carries information)
    LQX4  fresh-flow-type  -> FADE          (control: should underperform
                                             LQX2 for the same reason)

Universe widened to 26 liquid USDT perps (vs the 3-8 used everywhere
else in this project) specifically because this is an EVENT scanner --
frequency comes from watching many symbols for a rare event, not from a
high hit-rate on any single one. Cross-exchange basis dislocation
(Binance vs Bybit/OKX/spot) is explicitly deferred -- it needs new data
source integration this project does not have yet.

Discovery regime, as agreed: development window only, base+stress only,
judged on trades/day, expectancy_R, PF, per-symbol concentration --
frozen protocol only if something clears the bar (>=5 events/day
pooled, net R after stress costs >=0.15-0.25R).
"""
from collections import Counter
from dataclasses import replace

import numpy as np
import talib

from l1_filter.scalp_strategy import ScalpConfig, resample_closed
from .cluster_scalp_simulator import execute_cluster
from .metrics_data import load_metrics
from .scalp_data import load_archives

TRADED = (
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT', 'SUIUSDT', 'DOGEUSDT',
    'AVAXUSDT', 'LINKUSDT', 'LTCUSDT', 'DOTUSDT', 'NEARUSDT', 'ATOMUSDT', 'APTUSDT', 'ARBUSDT',
    'OPUSDT', 'INJUSDT', 'FILUSDT', 'ICPUSDT', 'ETCUSDT', 'BCHUSDT', 'UNIUSDT', 'AAVEUSDT',
    'TRXUSDT', 'TONUSDT',
)
WARMUP, END = '2025-04-01', '2026-02-01'
DEV_START, DEV_END = '2025-08-01', '2026-02-01'

RANGE_ATR_MULT = 2.0
VOLUME_MULT = 2.0
VOLUME_AVG_LOOKBACK = 20
OI_LOOKBACK_BARS = 8       # 2h on 15m bars
OI_ZSCORE_WINDOW = 96      # 24h
OI_EXTREME_Z = 1.5
STOP_BUFFER_ATR_MULT = 0.15


def bounce_execution(name):
    return ScalpConfig(
        name=name, minutes=15, target_r=3.0, partial_r=1.0, partial_fraction=0.0,
        trailing=True, trail_atr=1.5, max_hold_minutes=180, risk_fraction=0.0020,
        max_notional_equity=0.50, daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
        min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
        margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
        fixed_margin_usd=25.0, fixed_risk_usd=0.50,
    )


def patient_execution(name):
    return ScalpConfig(
        name=name, minutes=15, target_r=8.0, partial_r=1.5, partial_fraction=0.0,
        trailing=True, trail_atr=2.5, max_hold_minutes=240, risk_fraction=0.0020,
        max_notional_equity=0.50, daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
        min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
        margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
        fixed_margin_usd=25.0, fixed_risk_usd=0.50,
    )


def build_features(minutes, metrics):
    bars = resample_closed(minutes, 15)
    high, low, close = bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy()
    bars['atr'] = talib.ATR(high, low, close, timeperiod=14)
    vol_base = bars.volume.shift(1).rolling(VOLUME_AVG_LOOKBACK, min_periods=VOLUME_AVG_LOOKBACK).mean()
    bars['volume_spike'] = bars.volume >= VOLUME_MULT * vol_base
    bar_range = bars.high - bars.low
    bars['range_spike'] = bar_range >= RANGE_ATR_MULT * bars.atr

    aligned = metrics.reindex(bars.index, method='ffill')
    bars = bars.join(aligned)
    bars['oi_change'] = bars.open_interest - bars.open_interest.shift(OI_LOOKBACK_BARS)
    mean = bars.oi_change.rolling(OI_ZSCORE_WINDOW, min_periods=OI_ZSCORE_WINDOW).mean()
    std = bars.oi_change.rolling(OI_ZSCORE_WINDOW, min_periods=OI_ZSCORE_WINDOW).std()
    bars['oi_zscore'] = (bars.oi_change - mean) / std.where(std > 0)
    return bars


def generate_events(bars, symbol):
    """Returns raw events (spike + OI classification), independent of
    which of the 4 variants will trade them."""
    n = len(bars)
    atr = bars.atr.to_numpy()
    high, low, close, open_ = (bars.high.to_numpy(), bars.low.to_numpy(),
                               bars.close.to_numpy(), bars.open.to_numpy())
    range_spike = bars.range_spike.to_numpy()
    volume_spike = bars.volume_spike.to_numpy()
    oi_zscore = bars.oi_zscore.to_numpy()

    events = []
    for i in range(n):
        if not (range_spike[i] and volume_spike[i]):
            continue
        if not np.isfinite(oi_zscore[i]) or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        if oi_zscore[i] <= -OI_EXTREME_Z:
            event_type = 'liquidation'
        elif oi_zscore[i] >= OI_EXTREME_Z:
            event_type = 'fresh_flow'
        else:
            continue
        move_side = 1 if close[i] > open_[i] else -1
        events.append({
            'i': i, 'timestamp': bars.index[i], 'move_side': move_side,
            'event_type': event_type, 'close': close[i], 'open': open_[i],
            'high': high[i], 'low': low[i], 'atr': atr[i], 'oi_zscore': oi_zscore[i],
        })
    return events


def _finalize(records):
    records.sort(key=lambda r: r['timestamp'])
    counts = Counter(r['timestamp'] for r in records)
    return [r for r in records if counts[r['timestamp']] == 1]


def signals_for_variant(events, symbol, event_type, trade_direction, tag):
    """trade_direction: 'fade' (against move_side) or 'with' (continuation)."""
    records = []
    for e in events:
        if e['event_type'] != event_type:
            continue
        side = -e['move_side'] if trade_direction == 'fade' else e['move_side']
        if trade_direction == 'fade':
            extreme = e['low'] if side == 1 else e['high']
            stop = extreme - side * STOP_BUFFER_ATR_MULT * e['atr']
        else:
            midpoint = (e['high'] + e['low']) / 2.0
            stop = midpoint
        reference = e['close']
        risk = side * (reference - stop)
        if risk <= 0:
            continue
        direction = 'long' if side == 1 else 'short'
        records.append({
            'timestamp': e['timestamp'], 'side': side, 'reference': float(reference),
            'stop': float(stop), 'min_stop_atr': 0.5, 'max_stop_atr': 5.0,
            'atr': float(e['atr']), 'score': 6, 'setup': f'{tag}_{symbol}',
            'setup_id': f'{tag}:v1:{symbol}:{direction}:{e["timestamp"].isoformat()}',
        })
    return _finalize(records)


VARIANTS = [
    ('LQX1_liquidation_fade', 'liquidation', 'fade', bounce_execution),
    ('LQX2_freshflow_continuation', 'fresh_flow', 'with', patient_execution),
    ('LQX3_liquidation_continuation_CONTROL', 'liquidation', 'with', patient_execution),
    ('LQX4_freshflow_fade_CONTROL', 'fresh_flow', 'fade', bounce_execution),
]


def summarize(summary, trades):
    longs = [t for t in trades if t['side'] == 'LONG']
    shorts = [t for t in trades if t['side'] == 'SHORT']
    per_symbol = {s: round(row['net_pnl'], 2) for s, row in summary['per_symbol'].items() if row['trades'] > 0}
    top_symbol_share = None
    if per_symbol:
        gross = sum(max(v, 0) for v in per_symbol.values())
        if gross > 0:
            top_symbol_share = round(max(max(v, 0) for v in per_symbol.values()) / gross * 100, 1)
    return {
        'trades': summary['trades'], 'PF': summary['profit_factor'],
        'expectancy_R': round(summary['mean_net_r'], 4) if summary['trades'] else None,
        'net_pnl': round(summary['net_pnl'], 2), 'max_DD_pct': round(summary['max_drawdown_pct'], 3),
        'long_n': len(longs), 'short_n': len(shorts),
        'top_symbol_gross_profit_share_pct': top_symbol_share,
        'n_symbols_traded': len(per_symbol),
    }


def main():
    cache = '/tmp/sentinel-scalp-cache'
    events_by_symbol = {}
    minutes_by_symbol = {}
    for symbol in TRADED:
        minutes, funding, _ = load_archives(symbol, WARMUP, END, cache)
        metrics, _ = load_metrics(symbol, WARMUP, END, cache)
        minutes_by_symbol[symbol] = (minutes, funding)
        bars = build_features(minutes, metrics)
        events_by_symbol[symbol] = generate_events(bars, symbol)
        print(symbol, 'events:', len(events_by_symbol[symbol]),
              'liquidation:', sum(1 for e in events_by_symbol[symbol] if e['event_type'] == 'liquidation'),
              'fresh_flow:', sum(1 for e in events_by_symbol[symbol] if e['event_type'] == 'fresh_flow'),
              flush=True)

    total_events = sum(len(v) for v in events_by_symbol.values())
    dev_days = 184
    print(f'\nTotal raw events across {len(TRADED)} symbols: {total_events} '
          f'({total_events/dev_days:.2f}/day pooled)')

    markets = {symbol: minutes_by_symbol[symbol] for symbol in TRADED}

    for variant_name, event_type, direction, exec_builder in VARIANTS:
        execution = exec_builder(variant_name)
        raw = {
            symbol: signals_for_variant(events_by_symbol[symbol], symbol, event_type, direction, variant_name)
            for symbol in TRADED
        }
        raw_count = sum(len(v) for v in raw.values())

        base = execute_cluster(markets, raw, execution, DEV_START, DEV_END,
                                initial_capital=250, symbol_priority=TRADED)
        stress_exec = replace(execution, maker_fee_bps=5.0, fee_bps=8.0,
                              slippage_bps=5.0, limit_penetration_bps=5.0)
        stress = execute_cluster(markets, raw, stress_exec, DEV_START, DEV_END,
                                  initial_capital=250, symbol_priority=TRADED)

        print(f'\n{"="*78}\n{variant_name}  (raw candidates: {raw_count}, {raw_count/dev_days:.2f}/day)\n{"="*78}')
        print('  base  :', summarize(base['summary'], base['trades']))
        print('  stress:', summarize(stress['summary'], stress['trades']))


if __name__ == '__main__':
    main()
