"""CE-2B final costed $250 backtest -- required regardless of what step 5
showed, per explicit instruction. Step 5 (run_ce2b_isolated_jump.py)
already established, on >1M 500ms observations per symbol, that the
Binance-vs-consensus residual almost never exceeds 15bps (BTC: 0 times
in 6 days; ETH/SOL: <1/day) and never safely clears this project's own
14-26bps round-trip cost. Threshold here is dropped to 5bps ONLY to have
enough events to run the engine at all -- this is a known sub-cost
signal by construction; a loss is the expected, not novel, outcome.
"""
from collections import Counter
from dataclasses import replace

import numpy as np
import pandas as pd
import talib

from l1_filter.scalp_strategy import ScalpConfig
from .cluster_scalp_simulator import execute_cluster
from .run_ce2_sync_check import DAYS, SYMBOLS
from .run_ce2b_isolated_jump import build_residual_series
from .scalp_data import load_archives

THRESHOLD_BPS = 5.0
STOP_ATR_MULT = 1.0
BINANCE_SCALP_CACHE = '/tmp/sentinel-scalp-cache'


def bounce_execution(name):
    return ScalpConfig(
        name=name, minutes=5, target_r=3.0, partial_r=1.0, partial_fraction=0.0,
        trailing=True, trail_atr=1.5, max_hold_minutes=30, risk_fraction=0.0020,
        max_notional_equity=0.50, daily_loss_fraction=0.006, fee_bps=5.0, slippage_bps=2.0,
        min_reward_cost_ratio=3.0, leverage=5.0, max_margin_fraction=0.10,
        margin_safety_reserve=0.01, maker_fee_bps=2.0, limit_penetration_bps=2.0,
        fixed_margin_usd=25.0, fixed_risk_usd=0.50,
    )


def main():
    markets, raw = {}, {}
    for symbol in SYMBOLS:
        minutes, funding, _ = load_archives(symbol, '2025-08-25', '2025-09-07', BINANCE_SCALP_CACHE)
        markets[symbol] = (minutes, funding)

        frames = []
        for day in DAYS:
            frame = build_residual_series(symbol, day)
            if frame is not None:
                frames.append(frame)
        if not frames:
            raw[symbol] = []
            continue
        combined = pd.concat(frames).sort_index()

        resampled_1m = minutes.resample('1min').agg(
            {'high': 'max', 'low': 'min', 'close': 'last'})
        atr_1m = pd.Series(
            talib.ATR(resampled_1m.high.to_numpy(), resampled_1m.low.to_numpy(),
                      resampled_1m.close.to_numpy(), timeperiod=14),
            index=resampled_1m.index)
        atr_at = atr_1m.reindex(combined.index, method='ffill')

        div = combined.residual_bps.to_numpy()
        atr = atr_at.to_numpy()
        price = combined.binance.to_numpy()
        records = []
        for i in range(1, len(combined)):
            if not np.isfinite(div[i]) or not np.isfinite(atr[i]) or atr[i] <= 0:
                continue
            was_extreme = abs(div[i - 1]) >= THRESHOLD_BPS if np.isfinite(div[i - 1]) else False
            if was_extreme:
                continue
            if div[i] >= THRESHOLD_BPS:
                side = -1
            elif div[i] <= -THRESHOLD_BPS:
                side = 1
            else:
                continue
            reference = price[i]
            stop = reference - side * STOP_ATR_MULT * atr[i]
            risk = side * (reference - stop)
            if risk <= 0:
                continue
            direction = 'long' if side == 1 else 'short'
            ts = combined.index[i]
            records.append({
                'timestamp': ts, 'side': side, 'reference': float(reference),
                'stop': float(stop), 'min_stop_atr': 0.3, 'max_stop_atr': 3.0,
                'atr': float(atr[i]), 'score': 6, 'setup': f'CE2B_{symbol}',
                'setup_id': f'CE2B:v1:{symbol}:{direction}:{ts.isoformat()}',
            })
        records.sort(key=lambda r: r['timestamp'])
        counts = Counter(r['timestamp'] for r in records)
        raw[symbol] = [r for r in records if counts[r['timestamp']] == 1]
        print(symbol, 'CE2B candidates:', len(raw[symbol]), flush=True)

    total = sum(len(v) for v in raw.values())
    print(f'\nTotal candidates: {total} ({total/len(DAYS):.2f}/day pooled, {len(SYMBOLS)} symbols)')

    execution = bounce_execution('CE2B_isolated_jump')
    base = execute_cluster(markets, raw, execution, '2025-09-01', '2025-09-07',
                            initial_capital=250, symbol_priority=SYMBOLS)
    stress_exec = replace(execution, maker_fee_bps=5.0, fee_bps=8.0,
                          slippage_bps=5.0, limit_penetration_bps=5.0)
    stress = execute_cluster(markets, raw, stress_exec, '2025-09-01', '2025-09-07',
                              initial_capital=250, symbol_priority=SYMBOLS)

    print('\n' + '=' * 78)
    print('CE-2B FULL $250 BACKTEST RESULT (2025-09-01 .. 2025-09-07, threshold=5bps)')
    print('=' * 78)
    print('BASE  :', base['summary'])
    print('STRESS:', stress['summary'])


if __name__ == '__main__':
    main()
