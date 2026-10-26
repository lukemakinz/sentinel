"""S46 historical characterization run -- IN-SAMPLE / DISCOVERY-AFFECTED,
NOT a validation gate (see docs/research/s46_funding_veto/protocol.json).
S20 H1's exact entry/exit plus one frozen veto: reject any candidate
whose most recently known funding rate (strictly before its own
timestamp) is negative or unknown. Reports trades, PF base/stress,
expectancy R, max drawdown, long/short split, per-symbol split, monthly
PnL, and the longest consecutive losing streak, for each of the three
historical windows. Nothing here feeds back into the rule -- it is
frozen regardless of what this script prints.
"""
from dataclasses import replace
from itertools import groupby

import pandas as pd

from l1_filter.order_block_oi_confirmation_scalp import oi_features
from l1_filter.order_block_oi_funding_veto_scalp import (
    generate_funding_vetoed_signals,
    s46_execution,
)
from .cluster_scalp_simulator import execute_cluster
from .metrics_data import load_metrics
from .scalp_data import load_archives

TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
WARMUP, END = '2025-04-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-08-01', '2026-02-01'),
    'validation': ('2026-02-01', '2026-04-01'),
    'retrospective_evaluation': ('2026-04-01', END),
}


def longest_losing_streak(trades):
    ordered = sorted(trades, key=lambda t: t['opened_at'])
    outcomes = ['L' if t['pnl'] < 0 else 'W' for t in ordered]
    longest = 0
    for key, group in groupby(outcomes):
        if key == 'L':
            longest = max(longest, len(list(group)))
    return longest


def main():
    cache = '/tmp/sentinel-scalp-cache'
    config = s46_execution()

    data, raw = {}, {}
    for symbol in TRADED:
        minutes, funding, _ = load_archives(symbol, WARMUP, END, cache)
        metrics, _ = load_metrics(symbol, WARMUP, END, cache)
        data[symbol] = minutes, funding, metrics
        bars = oi_features(minutes, metrics, config)
        raw[symbol] = generate_funding_vetoed_signals(bars, funding, symbol)

    markets = {symbol: (data[symbol][0], data[symbol][1]) for symbol in TRADED}

    print('#' * 78)
    print('# S46 -- IN-SAMPLE / DISCOVERY-AFFECTED. NOT A VALIDATION RESULT.')
    print('# The only legitimate gate for this rule is genuinely new forward data.')
    print('#' * 78)

    for window, (start, end) in WINDOWS.items():
        base = execute_cluster(markets, raw, config.execution(), start, end,
                                initial_capital=250, symbol_priority=TRADED)
        stress_exec = replace(config.execution(), maker_fee_bps=5.0, fee_bps=8.0,
                              slippage_bps=5.0, limit_penetration_bps=5.0)
        stress = execute_cluster(markets, raw, stress_exec, start, end,
                                  initial_capital=250, symbol_priority=TRADED)

        trades = base['trades']
        s = base['summary']
        longs = [t for t in trades if t['side'] == 'LONG']
        shorts = [t for t in trades if t['side'] == 'SHORT']

        def pf(group):
            gains = sum(t['pnl'] for t in group if t['pnl'] > 0)
            losses = -sum(t['pnl'] for t in group if t['pnl'] < 0)
            return round(gains / losses, 3) if losses > 0 else (float('inf') if gains > 0 else None)

        print(f'\n{"="*78}\n{window} ({start} to {end})\n{"="*78}')
        print(f'  trades={s["trades"]}  wins={s["wins"]}  win_rate={s["win_rate_pct"]:.1f}%')
        print(f'  PF base={s["profit_factor"]}  PF stress={stress["summary"]["profit_factor"]}')
        print(f'  net_pnl base=${s["net_pnl"]:.2f}  net_pnl stress=${stress["summary"]["net_pnl"]:.2f}')
        print(f'  expectancy (mean R) = {s["mean_net_r"]:.4f}')
        print(f'  max_drawdown_pct = {s["max_drawdown_pct"]:.3f}%')
        print(f'  longest losing streak = {longest_losing_streak(trades)} trades')
        print(f'  LONG:  n={len(longs)}  PF={pf(longs)}')
        print(f'  SHORT: n={len(shorts)}  PF={pf(shorts)}')
        print('  per_symbol:')
        for symbol, row in s['per_symbol'].items():
            print(f'    {symbol:9s} trades={row["trades"]:>3d} net_pnl=${row["net_pnl"]:.2f}')
        print('  per_month:')
        for month, row in s['per_month'].items():
            print(f'    {month}  trades={row["trades"]:>3d}  pnl=${row["pnl"]:.2f}')


if __name__ == '__main__':
    main()
