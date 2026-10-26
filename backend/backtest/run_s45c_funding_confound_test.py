"""S45c: the decisive confound test for the negative-funding candidate
before it may be frozen as S46. Still purely diagnostic -- no new entry
logic, no filter applied. Three layers, exactly as specified:

  A) leave-one-symbol-out: negative vs non_negative PF/summary per window,
     with each symbol excluded in turn. The interesting row is
     "exclude SOLUSDT" -- if negative funding still looks bad without
     SOL, "it's just SOL" stops being a good objection.

  B) OLS: r_multiple ~ negative_funding + C(symbol) + C(window) + C(side),
     HC3 robust errors, pooled across all three windows' realized trades.

  C) Bootstrap (10000 resamples, refitting the same OLS each time) of the
     negative_funding coefficient: median, 95% CI, P(beta < 0).

  D) funding_age_hours percentiles (sanity check only, not filtered on).

Decision rule frozen BEFORE this script's output is read (verbatim from
the user's instruction):
    P(beta<0) >= 95% AND leave-one-out does not make the effect vanish
        without SOL                                  -> S46 GO
    beta negative but 95% CI straddles zero            -> promising,
        forward-only, no promotion
    effect vanishes once SOL is excluded                -> S46 REJECT
    beta ~= 0 or positive after controlling for
        symbol/side/window                             -> S46 REJECT
No single-symbol PF<1-in-every-window requirement (too strict at n=8
per cell); no SOL-only version under any outcome (that would be exactly
the post-hoc symbol-selection this project's own history (S24->S28,
S40->S41, S43, S44C) has already shown to manufacture illusory edges).
"""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

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
    prior = series[series.index < ts]
    if prior.empty:
        return None, None
    rate = float(prior.iloc[-1])
    age_hours = (pd.Timestamp(ts) - prior.index[-1]).total_seconds() / 3600
    return rate, age_hours


def summarize(group):
    if not group:
        return {'n': 0, 'PF': None, 'expectancy_R': None}
    gains = sum(t['pnl'] for t in group if t['pnl'] > 0)
    losses = -sum(t['pnl'] for t in group if t['pnl'] < 0)
    return {
        'n': len(group),
        'PF': round(gains / losses, 3) if losses > 0 else (float('inf') if gains > 0 else None),
        'expectancy_R': round(sum(t['r_multiple'] for t in group) / len(group), 3),
    }


def fmt(s):
    return f"n={s['n']:>4d} PF={str(s['PF']):>7s} E[R]={str(s['expectancy_R']):>7s}"


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

    all_trades = []
    for window, (start, end) in WINDOWS.items():
        result = execute_cluster(markets, raw, config.execution(), start, end,
                                  initial_capital=250, symbol_priority=TRADED)
        trades = result['trades']
        for t in trades:
            rate, age = funding_rate_at(funding_at, t['symbol'], t['opened_at'])
            t['funding_rate'] = rate
            t['funding_age_hours'] = age
            t['funding_state'] = None if rate is None else ('negative' if rate < 0 else 'non_negative')
            t['window'] = window
        all_trades.extend(trades)

    # ---------------------------------------------------------------
    # A) leave-one-symbol-out, per window
    # ---------------------------------------------------------------
    print('=' * 78)
    print('A) LEAVE-ONE-SYMBOL-OUT')
    print('=' * 78)
    for window in WINDOWS:
        window_trades = [t for t in all_trades if t['window'] == window]
        print(f'\n-- {window} --')
        for excluded in TRADED:
            subset = [t for t in window_trades if t['symbol'] != excluded]
            for state in ('negative', 'non_negative'):
                grp = [t for t in subset if t['funding_state'] == state]
                print(f'  exclude {excluded:9s} {state:13s} {fmt(summarize(grp))}')

    # ---------------------------------------------------------------
    # B) OLS: r_multiple ~ negative_funding + symbol + window + side
    # ---------------------------------------------------------------
    df = pd.DataFrame([
        {
            'r_multiple': t['r_multiple'],
            'funding_state': t['funding_state'],
            'symbol': t['symbol'],
            'window': t['window'],
            'side': t['side'],
            'funding_age_hours': t['funding_age_hours'],
        }
        for t in all_trades if t['funding_state'] is not None
    ])
    df['negative_funding'] = (df['funding_state'] == 'negative').astype(int)

    print('\n' + '=' * 78)
    print('B) OLS: r_multiple ~ negative_funding + C(symbol) + C(window) + C(side)')
    print('=' * 78)
    model = smf.ols(
        'r_multiple ~ negative_funding + C(symbol) + C(window) + C(side)',
        data=df,
    ).fit(cov_type='HC3')
    print(model.summary())

    # ---------------------------------------------------------------
    # C) bootstrap of the negative_funding coefficient
    # ---------------------------------------------------------------
    print('\n' + '=' * 78)
    print('C) BOOTSTRAP (10000 resamples) of negative_funding coefficient')
    print('=' * 78)
    rng = np.random.default_rng(42)
    effects = []
    for _ in range(10000):
        sample = df.sample(len(df), replace=True, random_state=int(rng.integers(0, 2**31 - 1)))
        if sample['negative_funding'].nunique() < 2:
            continue
        try:
            m = smf.ols(
                'r_multiple ~ negative_funding + C(symbol) + C(window) + C(side)',
                data=sample,
            ).fit()
            effects.append(m.params['negative_funding'])
        except Exception:
            continue
    effects = np.asarray(effects)
    print('valid bootstrap draws:', len(effects), '/ 10000')
    print('beta median:', np.median(effects))
    print('95% bootstrap CI:', np.quantile(effects, [0.025, 0.975]))
    print('P(beta < 0):', np.mean(effects < 0))

    # ---------------------------------------------------------------
    # D) funding_age_hours sanity check
    # ---------------------------------------------------------------
    print('\n' + '=' * 78)
    print('D) funding_age_hours percentiles (recorded only, not filtered on)')
    print('=' * 78)
    ages = df['funding_age_hours'].dropna()
    print(ages.quantile([0, .25, .50, .75, .95, 1]))


if __name__ == '__main__':
    main()
