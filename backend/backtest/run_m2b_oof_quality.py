"""M2b -- fixes two issues in M2 and adds proper out-of-fold scoring:

  1. volume_ratio was described as a feature but never actually added to
     the record or the regression -- genuinely untested. Added here.
  2. M2's quartile read scored fitted values on the SAME data the model
     was fit on -- guaranteed to show separation even from pure noise.
     Here the development window is split chronologically in half:
     model fit on the FIRST half only, quantile cutoffs computed on the
     first half's fitted distribution, and every number reported below
     is computed on the SECOND half only, scored by a model that never
     saw it.

Reports expectancy AND trades/day together for baseline / top-50% /
top-25%, because M2's Q4 result independently killed frequency (0.69
trades/day) even before being exposed as a same-data artifact -- both
matter for the $5/day target, not expectancy alone.

No new thresholds, no symbol selection, no new features beyond fixing
the volume_ratio omission. If this does not show positive OOF
expectancy, bar-level event-quality filtering is closed -- no M2c/d/e.
"""
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from l1_filter.scalp_strategy import resample_closed
from .cluster_scalp_simulator import execute_cluster
from .metrics_data import load_metrics
from .run_lqx1_discovery import VOLUME_AVG_LOOKBACK, build_features, generate_events, patient_execution
from .scalp_data import load_archives

TRADED = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT', 'SUIUSDT', 'DOGEUSDT')
WARMUP, END = '2025-04-01', '2026-02-01'
DEV_START, DEV_END = '2025-08-01', '2026-02-01'
SPLIT_DATE = pd.Timestamp('2025-11-01', tz='UTC')  # roughly the midpoint of the 184-day dev window

FEATURES = 'move_size_atr + volume_ratio + oi_zscore + funding_sign + btc_return_15m + idiosyncratic_bps'


def funding_rate_at(funding_series, ts):
    prior = funding_series[funding_series.index < ts]
    if prior.empty:
        return None
    return float(prior.iloc[-1])


def btc_return_series(cache):
    minutes, _, _ = load_archives('BTCUSDT', WARMUP, END, cache)
    bars = resample_closed(minutes, 15)
    return bars.close.pct_change(1) * 10_000


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
        vol_base = bars.volume.shift(1).rolling(VOLUME_AVG_LOOKBACK, min_periods=VOLUME_AVG_LOOKBACK).mean()
        events = generate_events(bars, symbol)

        execution = patient_execution('M2b_freshflow_continuation')
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
            vb = vol_base.get(e['timestamp'], np.nan)
            vol_ratio = float(bars.volume.get(e['timestamp'], np.nan) / vb) if vb and np.isfinite(vb) and vb > 0 else np.nan
            signals.append({
                'timestamp': e['timestamp'], 'side': side, 'reference': float(reference),
                'stop': float(stop), 'min_stop_atr': 0.5, 'max_stop_atr': 5.0,
                'atr': float(e['atr']), 'score': 6, 'setup': f'M2b_{symbol}',
                'setup_id': f'M2b:v1:{symbol}:{direction}:{e["timestamp"].isoformat()}',
                'move_size_atr': (e['high'] - e['low']) / e['atr'],
                'volume_ratio': vol_ratio,
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
                'r_multiple': t['r_multiple'], 'symbol': symbol, 'timestamp': feat['timestamp'],
                'move_size_atr': feat['move_size_atr'], 'volume_ratio': feat['volume_ratio'],
                'oi_zscore': feat['oi_zscore'], 'funding_sign': feat['funding_sign'],
                'btc_return_15m': feat['btc_return_15m'], 'idiosyncratic_bps': feat['idiosyncratic_bps'],
            })
        print(symbol, 'candidates:', len(signals), 'realized:', len(result['trades']), flush=True)

    df = pd.DataFrame(all_candidates).dropna()
    train = df[df.timestamp < SPLIT_DATE].copy()
    test = df[df.timestamp >= SPLIT_DATE].copy()
    print(f'\nTrain (before {SPLIT_DATE.date()}): n={len(train)}, expectancy={train.r_multiple.mean():.4f}R')
    print(f'Test  (from  {SPLIT_DATE.date()}): n={len(test)}, expectancy={test.r_multiple.mean():.4f}R')
    dev_days = 184
    train_days = (SPLIT_DATE - pd.Timestamp(DEV_START, tz='UTC')).days
    test_days = dev_days - train_days

    model = smf.ols(f'r_multiple ~ {FEATURES}', data=train).fit(cov_type='HC3')
    print('\n' + '=' * 78)
    print('OLS fit on TRAIN half only')
    print('=' * 78)
    print(model.summary().tables[0])
    print(model.summary().tables[1])

    train['fitted'] = model.fittedvalues
    cut_50 = train.fitted.median()
    cut_75 = train.fitted.quantile(0.75)

    test['fitted'] = model.predict(test)

    def report(label, group, days):
        if len(group) == 0:
            print(f'  {label}: n=0')
            return
        gains = group.r_multiple[group.r_multiple > 0].sum()
        losses = -group.r_multiple[group.r_multiple < 0].sum()
        pf = gains / losses if losses > 0 else float('inf')
        print(f'  {label}: n={len(group):>4d}  trades/day={len(group)/days:.3f}  '
              f'expectancy={group.r_multiple.mean():>7.3f}R  PF={pf:.3f}')

    print(f'\n{"="*78}\nOUT-OF-FOLD result on TEST half ({test_days} days), '
          f'cutoffs from TRAIN fitted distribution\n{"="*78}')
    report('baseline (all test candidates)', test, test_days)
    report('top-50% by OOF score', test[test.fitted >= cut_50], test_days)
    report('top-25% by OOF score', test[test.fitted >= cut_75], test_days)


if __name__ == '__main__':
    main()
