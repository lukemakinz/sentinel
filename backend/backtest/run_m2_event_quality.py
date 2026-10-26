"""M2 -- event-quality meta-selection on top of LQX2 (fresh_flow ->
continuation, the least-bad of the four LQX-1 variants: PF 0.71 base,
expectancy -0.165R, n=184). Question: which subset of these candidates
has positive net expectancy, using features known at entry time --
NOT a new strategy from scratch, a quality filter on an already-found
event pool, per the agreed direction.

Per-candidate outcomes are computed one symbol at a time (each symbol's
own LQX2 candidates run through execute_cluster alone, avoiding the
8-way shared-position competition of the LQX-1 discovery run) so nearly
every candidate gets a chance to realize an outcome for this feature
analysis -- a deliberately more complete dataset than the portfolio-
level backtest, appropriate for a signal-quality study, not a capital
allocation study.

Features (all known causally at the entry bar):
    move_size_atr   -- the spike bar's range / ATR (already >=2.0 by
                        construction; the exact size still varies)
    volume_ratio    -- volume / 20-bar average (already >=2.0)
    oi_zscore       -- signed OI z-score (already >=+1.5 for fresh_flow)
    funding_sign    -- +1/0/-1, most recent known funding rate strictly
                        before the event (S46's funding_rate_at, reused)
    btc_return_15m  -- BTC's own trailing 15-minute return at the event
                        timestamp (uses BTC's own 15m bars, causal)
    idiosyncratic_bps -- the symbol's own bar return (bps) MINUS BTC's
                        concurrent 15m return (bps) -- the specific
                        cross-sectional signal flagged as most promising:
                        a large idiosyncratic move (symbol moves, BTC
                        doesn't) vs a market-wide move (both move
                        together) are argued to be different phenomena.

Method: OLS of r_multiple on these features (HC3 robust SE) -- not a
hand-tuned threshold grid -- then check whether the top quartile by
fitted score has a materially different (and positive) realized
expectancy than the bottom quartile, out of the SAME pool (an in-sample
signal-quality read, explicitly not a validated result).
"""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import talib

from l1_filter.scalp_strategy import resample_closed
from .cluster_scalp_simulator import execute_cluster
from .metrics_data import load_metrics
from .run_lqx1_discovery import (
    STOP_BUFFER_ATR_MULT, build_features, generate_events, patient_execution,
)
from .scalp_data import load_archives

TRADED = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT', 'SUIUSDT', 'DOGEUSDT')
WARMUP, END = '2025-04-01', '2026-02-01'
DEV_START, DEV_END = '2025-08-01', '2026-02-01'


def funding_rate_at(funding_series, ts):
    prior = funding_series[funding_series.index < ts]
    if prior.empty:
        return None
    return float(prior.iloc[-1])


def btc_return_series(cache):
    minutes, _, _ = load_archives('BTCUSDT', WARMUP, END, cache)
    bars = resample_closed(minutes, 15)
    ret_15m = bars.close.pct_change(1) * 10_000  # bps, one 15m bar's own return
    return ret_15m


def main():
    cache = '/tmp/sentinel-scalp-cache'
    btc_ret = btc_return_series(cache)

    data = {}
    all_candidates = []
    for symbol in TRADED:
        minutes, funding, _ = load_archives(symbol, WARMUP, END, cache)
        metrics, _ = load_metrics(symbol, WARMUP, END, cache)
        data[symbol] = (minutes, funding)
        bars = build_features(minutes, metrics)
        events = generate_events(bars, symbol)

        execution = patient_execution('M2_freshflow_continuation')
        signals = []
        for e in events:
            if e['event_type'] != 'fresh_flow':
                continue
            side = e['move_side']
            midpoint = (e['high'] + e['low']) / 2.0
            stop = midpoint
            reference = e['close']
            risk = side * (reference - stop)
            if risk <= 0:
                continue
            direction = 'long' if side == 1 else 'short'
            symbol_bps = side * (reference / e['open'] - 1.0) * 10_000
            btc_bps = btc_ret.get(e['timestamp'], np.nan)
            signals.append({
                'timestamp': e['timestamp'], 'side': side, 'reference': float(reference),
                'stop': float(stop), 'min_stop_atr': 0.5, 'max_stop_atr': 5.0,
                'atr': float(e['atr']), 'score': 6, 'setup': f'M2_{symbol}',
                'setup_id': f'M2:v1:{symbol}:{direction}:{e["timestamp"].isoformat()}',
                'move_size_atr': (e['high'] - e['low']) / e['atr'],
                'oi_zscore': e['oi_zscore'],
                'funding_sign': np.sign(funding_rate_at(funding, e['timestamp']) or 0.0),
                'btc_return_15m': float(btc_bps) if np.isfinite(btc_bps) else np.nan,
                'idiosyncratic_bps': float(symbol_bps - side * btc_bps) if np.isfinite(btc_bps) else np.nan,
                'symbol': symbol,
            })

        market = {symbol: data[symbol]}
        raw = {symbol: signals}
        result = execute_cluster(market, raw, execution, DEV_START, DEV_END,
                                  initial_capital=250, symbol_priority=(symbol,))
        by_setup_id = {s['setup_id']: s for s in signals}
        for t in result['trades']:
            feat = by_setup_id.get(t['setup_id'])
            if feat is None:
                continue
            all_candidates.append({
                'r_multiple': t['r_multiple'], 'symbol': symbol,
                'move_size_atr': feat['move_size_atr'], 'oi_zscore': feat['oi_zscore'],
                'funding_sign': feat['funding_sign'], 'btc_return_15m': feat['btc_return_15m'],
                'idiosyncratic_bps': feat['idiosyncratic_bps'],
            })
        print(symbol, 'candidates:', len(signals), 'realized:', len(result['trades']), flush=True)

    df = pd.DataFrame(all_candidates).dropna()
    print(f'\nTotal realized candidates with complete features: {len(df)}')
    print(f'Baseline (unfiltered) expectancy: {df.r_multiple.mean():.4f}R, n={len(df)}')

    print('\n' + '=' * 78)
    print('OLS: r_multiple ~ move_size_atr + oi_zscore + funding_sign + '
          'btc_return_15m + idiosyncratic_bps + C(symbol)')
    print('=' * 78)
    model = smf.ols(
        'r_multiple ~ move_size_atr + oi_zscore + funding_sign + btc_return_15m + '
        'idiosyncratic_bps + C(symbol)', data=df,
    ).fit(cov_type='HC3')
    print(model.summary())

    df['fitted'] = model.fittedvalues
    df['quartile'] = pd.qcut(df.fitted, 4, labels=['Q1_worst', 'Q2', 'Q3', 'Q4_best'])
    print('\n' + '=' * 78)
    print('Realized expectancy by fitted-score quartile (in-sample signal-quality read)')
    print('=' * 78)
    for q, g in df.groupby('quartile', observed=True):
        gains = g.r_multiple[g.r_multiple > 0].sum()
        losses = -g.r_multiple[g.r_multiple < 0].sum()
        pf = gains / losses if losses > 0 else float('inf')
        print(f'  {q}: n={len(g):>4d}  mean_R={g.r_multiple.mean():>7.3f}  PF={pf:.3f}')

    print('\nTop-quartile per-symbol breakdown (concentration check):')
    top = df[df.quartile == 'Q4_best']
    print(top.groupby('symbol').agg(n=('r_multiple', 'size'), mean_R=('r_multiple', 'mean')))


if __name__ == '__main__':
    main()
