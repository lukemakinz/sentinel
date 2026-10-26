"""S45b: refined funding diagnostic on S20 H1's already-realized trades
(no new entry logic, no filter applied yet -- that is S46, contingent on
this). Fixes two issues in the S45 funding tagging and adds the two
breakdowns needed to rule out a LONG/SHORT or single-symbol confound
before funding gets to become an actual filter:

  1. `< ts` instead of `<= ts` when looking up the most recent funding
     rate before a trade's entry -- conservative, avoids treating a
     rate published/settled exactly at the entry minute as already known.
  2. funding_state is now the frozen binary split requested: `negative`
     (rate < 0) vs `non_negative` (rate >= 0) -- no 'zero' bucket, no
     threshold to tune.
  3. funding_age_hours is recorded (not filtered on) alongside the rate,
     so staleness can be inspected separately.
  4. Reports funding_state x LONG/SHORT and funding_state x symbol,
     per window, to check whether the negative-funding effect is a
     genuine market-positioning signal or a proxy for one side or one
     symbol dominating the sample.
"""
import pandas as pd

from l1_filter.order_block_oi_confirmation_scalp import (
    OrderBlockOIConfig,
    generate_order_block_oi_signals,
    oi_features,
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


def funding_rate_at(funding_at, symbol, ts):
    series = funding_at[symbol]
    prior = series[series.index < ts]          # strict: '< ts', not '<= ts'
    if prior.empty:
        return None, None
    rate = float(prior.iloc[-1])
    funding_ts = prior.index[-1]
    age_hours = (pd.Timestamp(ts) - funding_ts).total_seconds() / 3600
    return rate, age_hours


def summarize(group):
    if not group:
        return {'n': 0, 'PF': None, 'expectancy_R': None, 'win_rate': None}
    gains = sum(t['pnl'] for t in group if t['pnl'] > 0)
    losses = -sum(t['pnl'] for t in group if t['pnl'] < 0)
    wins = sum(1 for t in group if t['pnl'] > 0)
    return {
        'n': len(group),
        'PF': round(gains / losses, 3) if losses > 0 else (float('inf') if gains > 0 else None),
        'expectancy_R': round(sum(t['r_multiple'] for t in group) / len(group), 3),
        'win_rate': round(wins / len(group), 3),
    }


def fmt(s):
    return f"n={s['n']:>4d} PF={str(s['PF']):>7s} E[R]={str(s['expectancy_R']):>7s} WR={str(s['win_rate']):>6s}"


def main():
    cache = '/tmp/sentinel-scalp-cache'
    config = OrderBlockOIConfig('S20_H1_diagnostic', 'oi', partial_r=1.5, trail_atr=2.5, target_r=8.0)

    data, raw, funding_at = {}, {}, {}
    for symbol in TRADED:
        minutes, funding, _ = load_archives(symbol, WARMUP, END, cache)
        metrics, _ = load_metrics(symbol, WARMUP, END, cache)
        data[symbol] = minutes, funding, metrics
        funding_at[symbol] = funding
        bars = oi_features(minutes, metrics, config)
        raw[symbol] = generate_order_block_oi_signals(bars, config, symbol)

    markets = {symbol: (data[symbol][0], data[symbol][1]) for symbol in TRADED}

    for window, (start, end) in WINDOWS.items():
        result = execute_cluster(markets, raw, config.execution(), start, end,
                                  initial_capital=250, symbol_priority=TRADED)
        trades = result['trades']
        for t in trades:
            rate, age = funding_rate_at(funding_at, t['symbol'], t['opened_at'])
            t['funding_rate'] = rate
            t['funding_age_hours'] = age
            t['funding_state'] = None if rate is None else ('negative' if rate < 0 else 'non_negative')

        print(f'\n{"="*70}\n{window} ({start} to {end}) -- total realized: {len(trades)}\n{"="*70}')

        print('\n-- funding_state x ALL --')
        for state in ('negative', 'non_negative'):
            grp = [t for t in trades if t['funding_state'] == state]
            print(f'  {state:13s} {fmt(summarize(grp))}')

        print('\n-- funding_state x LONG/SHORT --')
        for state in ('negative', 'non_negative'):
            for side in ('LONG', 'SHORT'):
                grp = [t for t in trades if t['funding_state'] == state and t['side'] == side]
                print(f'  {state:13s} {side:5s} {fmt(summarize(grp))}')

        print('\n-- funding_state x symbol --')
        for state in ('negative', 'non_negative'):
            for symbol in TRADED:
                grp = [t for t in trades if t['funding_state'] == state and t['symbol'] == symbol]
                print(f'  {state:13s} {symbol:9s} {fmt(summarize(grp))}')

        ages = [t['funding_age_hours'] for t in trades if t['funding_age_hours'] is not None]
        if ages:
            print(f'\n-- funding_age_hours: min={min(ages):.2f} max={max(ages):.2f} '
                  f'mean={sum(ages)/len(ages):.2f} (recorded only, not filtered on)')


if __name__ == '__main__':
    main()
