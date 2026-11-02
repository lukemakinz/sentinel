"""S118: timeframe x parameter robustness, random control and confluence study.

Protocol: docs/research/s118_tf_robustness_confluence/protocol.json (frozen).
    PYTHONPATH=. ../env/bin/python -m backtest.run_s118_tf_robustness
"""
from __future__ import annotations

import itertools
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from l2_agents.strategies.h3b_trend_double_bottom import atr, pivots, rsi, trend_4h
from .auction_replay import load_bars
from .scalp_data import archive

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs' / 'research' / 's118_tf_robustness_confluence'
CACHE = os.environ.get('PAPER_FORWARD_CACHE', '/tmp/sentinel-scalp-cache')
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'XRPUSDT', 'ADAUSDT', 'DOGEUSDT',
           'MATICUSDT', 'LINKUSDT', 'BNBUSDT']
PERIOD = (pd.Timestamp('2024-01-01', tz='UTC'), pd.Timestamp('2026-10-01', tz='UTC'))
DATA_START = pd.Timestamp('2022-12-01', tz='UTC')
TF_PAIRS = {'15m': '1h', '1h': '4h', '4h': '1d'}
TF_MIN = {'1m': 1, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}
RISK_BAND = {'15m': (0.6, 3.0), '1h': (1.0, 6.0), '4h': (2.0, 12.0)}
WIDTHS, EQUALS, DIVS = [2, 3, 5], [0.25, 0.5, 1.0], [0.0, 2.0, 5.0]
EXITS = {'E1': (2.0, 72), 'E2': (None, 168)}
MIN_SEP, MAX_SEP, MIN_HEIGHT, MAX_AFTER, STOP_BUF = 5, 60, 1.0, 24, 0.25
TAKER, MAKER, SLIP = 5.0, 2.0, 10.0 / 10_000
ARM_MS = 3 * 60_000
MIN_TRAIN_TRADES = 30
REFERENCE = ('1h', 3, 0.5, 2.0, 'E2')


# ------------------------------------------------------------------ exits
def simulate(direction: int, entry: float, stop: float, h, l, c, target_r, hold_bars: int):
    """(net R, exit offset in bars) with resolver conventions."""
    risk = abs(entry - stop)
    h, l, c = h[:hold_bars], l[:hold_bars], c[:hold_bars]
    if risk <= 0 or len(c) == 0:
        return float('nan'), 0
    hits = np.flatnonzero(l <= stop) if direction > 0 else np.flatnonzero(h >= stop)
    first_stop = hits[0] if len(hits) else None
    first_target = None
    if target_r is not None:
        target = entry + direction * target_r * risk
        t_hits = np.flatnonzero(h >= target) if direction > 0 else np.flatnonzero(l <= target)
        first_target = t_hits[0] if len(t_hits) else None
    if first_stop is not None and (first_target is None or first_stop <= first_target):
        exit_price, fee, offset = stop * (1 - direction * SLIP), TAKER, int(first_stop)
    elif first_target is not None:
        exit_price, fee, offset = entry + direction * target_r * risk, MAKER, int(first_target)
    else:
        exit_price, fee, offset = c[-1] * (1 - direction * SLIP), TAKER, len(c) - 1
    gross = direction * (exit_price - entry) / risk
    return float(gross - (entry * TAKER + exit_price * fee) / 10_000 / risk), offset


# --------------------------------------------------------------- features
def adx(h, l, c, period=14):
    n = len(c)
    out = np.full(n, np.nan)
    if n <= 2 * period:
        return out
    up, dn = h[1:] - h[:-1], l[:-1] - l[1:]
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))

    def wilder(x):
        s = np.full(len(x), np.nan)
        s[period - 1] = x[:period].sum()
        for i in range(period, len(x)):
            s[i] = s[i - 1] - s[i - 1] / period + x[i]
        return s
    atr_s, p_s, m_s = wilder(tr), wilder(plus), wilder(minus)
    pdi, mdi = 100 * p_s / atr_s, 100 * m_s / atr_s
    dx = 100 * abs(pdi - mdi) / (pdi + mdi)
    adx_v = np.full(len(dx), np.nan)
    start = 2 * period - 1
    adx_v[start] = np.nanmean(dx[period - 1:start + 1])
    for i in range(start + 1, len(dx)):
        adx_v[i] = (adx_v[i - 1] * (period - 1) + dx[i]) / period
    out[1:] = adx_v
    return out


class Series:
    def __init__(self, bars):
        self.open_ms = bars.open_ms
        self.close_ms = bars.open_ms + bars.step_ms
        self.o, self.h, self.l, self.c, self.v = bars.o, bars.h, bars.l, bars.c, bars.v
        closes = self.c.tolist()
        self.rsi = np.array([np.nan if x is None else x for x in rsi(closes)])
        rows = [{'high': a, 'low': b, 'close': d} for a, b, d in zip(self.h, self.l, self.c)]
        self.atr = np.array([np.nan if x is None else x for x in atr(rows)])
        self._pivots = {}

    def piv(self, kind, width):
        key = (kind, width)
        if key not in self._pivots:
            values = (self.l if kind == 'low' else self.h).tolist()
            self._pivots[key] = pivots(values, kind, width)
        return self._pivots[key]

    def closed_count(self, t_ms):
        return int(np.searchsorted(self.close_ms, t_ms, side='right'))


def trend_at(series: Series, t_ms: int) -> tuple[str, float]:
    n = series.closed_count(t_ms)
    if n < 60:
        return 'UNKNOWN', 0.0
    closes = series.c[max(0, n - 300):n]
    rows = [{'close': x} for x in closes]
    state = trend_4h(rows)
    alpha20, alpha50 = 2 / 21, 2 / 51
    e20 = e50 = closes[0]
    for x in closes:
        e20 = alpha20 * x + (1 - alpha20) * e20
        e50 = alpha50 * x + (1 - alpha50) * e50
    a = series.atr[n - 1] if not np.isnan(series.atr[n - 1]) else 0.0
    return state, float((e20 - e50) / a) if a else 0.0


def detect_events(s: Series, trend: Series, daily: Series, btc_trend: Series | None,
                  funding: pd.Series, tf: str, width: int, equal: float, div: float) -> list[dict]:
    events = []
    n = len(s.c)
    band = RISK_BAND[tf]
    for direction, kind in ((1, 'low'), (-1, 'high')):
        ext = s.l if kind == 'low' else s.h
        P = s.piv(kind, width)
        for j, p2 in enumerate(P):
            conf = p2 + width
            nxt = P[j + 1] + width if j + 1 < len(P) else n
            win_end = min(p2 + MAX_AFTER, nxt - 1, n - 1)
            if conf > win_end or np.isnan(s.atr[p2]) or np.isnan(s.rsi[p2]):
                continue
            a = s.atr[p2]
            chosen = None
            for p1 in reversed(P[:j]):
                gap = p2 - p1
                if gap < MIN_SEP:
                    continue
                if gap > MAX_SEP:
                    break
                if np.isnan(s.rsi[p1]) or abs(ext[p2] - ext[p1]) > equal * a:
                    continue
                d = (s.rsi[p2] - s.rsi[p1]) * direction
                if d < div:
                    continue
                if direction > 0:
                    neck = s.h[p1 + 1:p2].max()
                    height = neck - max(s.l[p1], s.l[p2])
                else:
                    neck = s.l[p1 + 1:p2].min()
                    height = min(s.h[p1], s.h[p2]) - neck
                if height < MIN_HEIGHT * a:
                    continue
                chosen = (p1, neck, d, height)
                break
            if chosen is None:
                continue
            p1, neck, d, height = chosen
            after = s.c[p2 + 1:win_end + 1]
            beyond = np.flatnonzero(after > neck) if direction > 0 else np.flatnonzero(after < neck)
            if not len(beyond):
                continue
            L = p2 + 1 + int(beyond[0])
            if L < conf:
                continue  # broke before p2 was confirmed: the plugin never sees a first break
            t_ms = int(s.close_ms[L])
            state, strength = trend_at(trend, t_ms)
            if state != ('UP' if direction > 0 else 'DOWN'):
                continue
            stop = (min(s.l[p1], s.l[p2]) - STOP_BUF * a) if direction > 0 else (max(s.h[p1], s.h[p2]) + STOP_BUF * a)
            ref = s.c[L]
            risk_pct = abs(ref - stop) / ref * 100
            if not band[0] <= risk_pct <= band[1]:
                continue
            # features (all causal at bar L)
            dn = daily.closed_count(t_ms)
            sma200 = daily.c[dn - 200:dn].mean() if dn >= 200 else np.nan
            lookback = max(0, L - int(365 * 1440 / TF_MIN[tf]))
            atr_hist = s.atr[lookback:L + 1]
            atr_hist = atr_hist[~np.isnan(atr_hist)]
            prior_v = s.v[max(0, L - 20):L]
            f_rate = (funding[funding.index < pd.Timestamp(t_ms, unit='ms', tz='UTC')]
                      if len(funding) else funding)
            btc_state = trend_at(btc_trend, t_ms)[0] if btc_trend is not None else None
            hour = pd.Timestamp(t_ms, unit='ms', tz='UTC').hour
            events.append({
                't_ms': t_ms, 'direction': direction, 'stop': float(stop), 'ref': float(ref),
                'risk_pct': float(risk_pct),
                'f_trend_strength_htf': strength * direction,
                'f_daily_trend': (ref / sma200 - 1) * 100 * direction if sma200 == sma200 else np.nan,
                'f_adx': float(s.adx[L]) if hasattr(s, 'adx') else np.nan,
                'f_break_volume_ratio': float(s.v[L] / np.median(prior_v)) if len(prior_v) and np.median(prior_v) > 0 else np.nan,
                'f_rsi_at_p2': float(s.rsi[p2]),
                'f_divergence': float(d),
                'f_height_atr': float(height / a),
                'f_risk_pct': float(risk_pct),
                'f_atr_percentile': float((atr_hist <= s.atr[L]).mean()) if len(atr_hist) else np.nan,
                'f_hour_bucket': 0 if hour < 8 else 1 if hour < 16 else 2,
                'f_btc_alignment': (np.nan if btc_state is None else
                                    float(btc_state == ('UP' if direction > 0 else 'DOWN'))),
                'f_funding': float(-f_rate.iloc[-1] * direction) if len(f_rate) else np.nan,
            })
    return sorted(events, key=lambda e: e['t_ms'])


def run_trades(events: list[dict], m1, exit_key: str, tf: str) -> list[dict]:
    target_r, hold_bars_tf = EXITS[exit_key]
    hold = hold_bars_tf * TF_MIN[tf] - 1
    start_ms, end_ms = PERIOD[0].value // 10**6, PERIOD[1].value // 10**6
    busy, out = 0, []
    for e in events:
        if not start_ms <= e['t_ms'] < end_ms or e['t_ms'] < busy:
            continue
        idx = int(np.searchsorted(m1.open_ms, e['t_ms'] + ARM_MS, side='left'))
        if idx >= len(m1.c):
            continue
        d, raw = e['direction'], m1.c[idx]
        if (d > 0 and raw <= e['stop']) or (d < 0 and raw >= e['stop']):
            busy = int(m1.open_ms[idx]) + 60_000
            continue  # pre-invalidated
        entry = raw * (1 + d * SLIP)
        w = slice(idx + 1, idx + 1 + hold)
        net, offset = simulate(d, entry, e['stop'], m1.h[w], m1.l[w], m1.c[w], target_r, hold)
        if net != net:
            continue
        busy = int(m1.open_ms[min(idx + 1 + offset, len(m1.c) - 1)]) + 60_000
        out.append({**e, 'net_r': net, 'entry_idx': idx})
    return out


def random_control(trades: pd.DataFrame, minutes: dict, exit_key: str, tf: str,
                   rng: np.random.Generator, per_trade: int = 20) -> pd.Series:
    target_r, hold_bars_tf = EXITS[exit_key]
    hold = hold_bars_tf * TF_MIN[tf] - 1
    diffs = []
    for _, t in trades.iterrows():
        m1 = minutes[t.symbol]
        years = m1.years
        pool = np.flatnonzero((years == t.year) & (np.arange(len(m1.c)) < len(m1.c) - hold - 2))
        vals = []
        for j in rng.choice(pool, size=per_trade, replace=False):
            d, raw = int(t.direction), m1.c[j]
            entry = raw * (1 + d * SLIP)
            stop = entry - d * t.risk_pct / 100 * entry
            w = slice(j + 1, j + 1 + hold)
            vals.append(simulate(d, entry, stop, m1.h[w], m1.l[w], m1.c[w], target_r, hold)[0])
        diffs.append(t.net_r - float(np.nanmean(vals)))
    return pd.Series(diffs, index=trades.index)


def day_ci(values, days, reps=5000, seed=1):
    f = pd.DataFrame({'v': np.asarray(values, float), 'd': np.asarray(days)}).dropna()
    if f.empty:
        return [None, None]
    g = f.groupby('d').v.agg(['sum', 'count'])
    s_, c_ = g['sum'].to_numpy(), g['count'].to_numpy()
    p = np.random.default_rng(seed).integers(0, len(s_), size=(reps, len(s_)))
    m = s_[p].sum(axis=1) / c_[p].sum(axis=1)
    return [round(float(np.quantile(m, 0.025)), 4), round(float(np.quantile(m, 0.975)), 4)]


def spearman_perm(x, y, reps=10_000, seed=2):
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    if len(x) < 30:
        return float('nan'), 1.0, int(len(x))
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(seed)
    perms = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(reps)])
    return rho, float((np.abs(perms) >= abs(rho)).mean()), int(len(x))


def benjamini_hochberg(pvals: dict, q=0.10) -> set:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, keep = len(items), set()
    for rank, (k, p) in enumerate(items, 1):
        if p <= q * rank / m:
            keep = {kk for kk, _ in items[:rank]}
    return keep


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(118)
    minutes, series = {}, {}
    for sym in SYMBOLS:
        m1 = load_bars(sym, '1m', PERIOD[0] - pd.Timedelta(days=2), PERIOD[1] + pd.Timedelta(days=30), CACHE)
        m1.years = pd.to_datetime(m1.open_ms, unit='ms', utc=True).year.to_numpy()
        minutes[sym] = m1
        for tf in ('15m', '1h', '4h', '1d'):
            series[(sym, tf)] = Series(load_bars(sym, tf, DATA_START, PERIOD[1], CACHE))
        for tf in ('15m', '1h', '4h'):
            s = series[(sym, tf)]
            s.adx = adx(s.h, s.l, s.c)
        print(f'loaded {sym}', flush=True)
    funding = {}
    for sym in SYMBOLS:
        parts = []
        for m in pd.period_range('2023-12', '2026-09', freq='M'):
            try:
                raw, _ = archive(sym, str(m), 'fundingRate', CACHE)
                idx = pd.to_datetime(raw.calc_time, unit='ms', utc=True)
                parts.append(pd.Series(raw.last_funding_rate.astype(float).to_numpy(), index=idx))
            except requests.HTTPError:
                pass
        funding[sym] = pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)

    rows = []
    for tf, (w, e, dv) in itertools.product(TF_PAIRS, itertools.product(WIDTHS, EQUALS, DIVS)):
        for sym in SYMBOLS:
            s, trend = series[(sym, tf)], series[(sym, TF_PAIRS[tf])]
            btc = None if sym == 'BTCUSDT' else series[('BTCUSDT', '4h')]
            events = detect_events(s, trend, series[(sym, '1d')], btc, funding[sym], tf, w, e, dv)
            for ex in EXITS:
                for t in run_trades(events, minutes[sym], ex, tf):
                    rows.append({**t, 'symbol': sym, 'tf': tf, 'width': w, 'equal': e, 'div': dv, 'exit': ex})
        print(f'{tf} w={w} e={e} d={dv}: cumulative trades {len(rows)}', flush=True)
    trades = pd.DataFrame(rows)
    trades['time'] = pd.to_datetime(trades.t_ms, unit='ms', utc=True)
    trades['year'] = trades.time.dt.year
    trades['day'] = trades.time.dt.floor('D')
    trades.to_csv(OUT / 'trades.csv.gz', index=False)
    keys = ['tf', 'width', 'equal', 'div', 'exit']

    # Steps 1-2: walk-forward over all configs
    folds, oos_parts = [], []
    for train_years, test_year in (([2024], 2025), ([2024, 2025], 2026)):
        train = trades[trades.year.isin(train_years)].groupby(keys).net_r.agg(['mean', 'count'])
        train = train[train['count'] >= MIN_TRAIN_TRADES]
        best = train['mean'].idxmax()
        tf_b, w_b, e_b, d_b, ex_b = best
        neigh = train.loc[[(tf_b, w, e, d, ex_b) for w, e, d in itertools.product(WIDTHS, EQUALS, DIVS)
                           if (w, e, d) != (w_b, e_b, d_b) and (tf_b, w, e, d, ex_b) in train.index], 'mean']
        test = trades[(trades.year == test_year)].set_index(keys).loc[[best]].reset_index()
        ctrl = random_control(test, minutes, ex_b, tf_b, rng)
        oos_parts.append(test.assign(ctrl_diff=ctrl.to_numpy()))
        folds.append({'train': train_years, 'test': test_year,
                      'chosen': dict(zip(keys, [best[0], int(best[1]), best[2], best[3], best[4]])),
                      'train_mean_r': round(float(train.loc[best, 'mean']), 4),
                      'train_trades': int(train.loc[best, 'count']),
                      'test_mean_r': round(float(test.net_r.mean()), 4), 'test_trades': int(len(test)),
                      'plateau_share_positive': round(float((neigh > 0).mean()), 3) if len(neigh) else None,
                      'random_control_diff': round(float(ctrl.mean()), 4)})
    oos = pd.concat(oos_parts)
    oos_ci = day_ci(oos.net_r, oos.day)
    ctrl_ci = day_ci(oos.ctrl_diff, oos.day)
    by_config = trades.groupby(keys).net_r.agg(['mean', 'count']).reset_index()
    by_tf_exit = trades.groupby(['tf', 'exit']).net_r.agg(['mean', 'count']).round(4).reset_index()
    by_tf_year = trades.groupby(['tf', 'exit', 'year']).net_r.mean().round(4).unstack().reset_index()
    passed = (oos_ci[0] is not None and oos_ci[0] > 0 and ctrl_ci[0] is not None and ctrl_ci[0] > 0
              and all((f['plateau_share_positive'] or 0) >= 0.5 for f in folds))

    # Step 3: confluence
    if passed:
        cfg = tuple(folds[-1]['chosen'][k] for k in keys)
    else:
        cfg = REFERENCE
    sub = trades.set_index(keys).loc[[cfg]].reset_index()
    dev, test26 = sub[sub.year.isin([2024, 2025])], sub[sub.year == 2026]
    features = [c for c in sub.columns if c.startswith('f_')]
    stats_f, pvals = {}, {}
    for f in features:
        rho, p, n = spearman_perm(dev[f].to_numpy(float), dev.net_r.to_numpy(float))
        stats_f[f] = {'rho': round(rho, 4) if rho == rho else None, 'p': round(p, 4), 'n': n}
        pvals[f] = p
    survivors = benjamini_hochberg(pvals)
    filters = {}
    for f in survivors:
        rho = stats_f[f]['rho']
        lo_cut, hi_cut = dev[f].quantile([1 / 3, 2 / 3])
        keep_dev = dev[f] >= lo_cut if rho > 0 else dev[f] <= hi_cut
        keep_test = test26[f] >= lo_cut if rho > 0 else test26[f] <= hi_cut
        kept = test26[keep_test]
        filters[f] = {'dev_kept_mean_r': round(float(dev[keep_dev].net_r.mean()), 4),
                      'test_unfiltered_mean_r': round(float(test26.net_r.mean()), 4),
                      'test_filtered_mean_r': round(float(kept.net_r.mean()), 4) if len(kept) else None,
                      'test_filtered_trades': int(len(kept)),
                      'test_filtered_ci95': day_ci(kept.net_r, kept.day)}

    summary = {
        'protocol': 'S118_TF_ROBUSTNESS_CONFLUENCE v1.0.0', 'total_trades_all_configs': int(len(trades)),
        'walk_forward': folds,
        'oos': {'trades': int(len(oos)), 'mean_net_r': round(float(oos.net_r.mean()), 4), 'ci95': oos_ci,
                'random_control_diff_mean': round(float(oos.ctrl_diff.mean()), 4),
                'random_control_ci95': ctrl_ci},
        'by_tf_exit_all_years': by_tf_exit.to_dict('records'),
        'by_tf_exit_year': by_tf_year.to_dict('records'),
        'share_configs_positive_full_period': round(float((by_config['mean'] > 0).mean()), 3),
        'top10_full_period_in_sample': by_config.sort_values('mean', ascending=False).head(10).round(4).to_dict('records'),
        'decision_steps_1_2': 'PASS_TO_NEW_PROTOCOL' if passed else 'REJECTED',
        'confluence': {'trade_set': dict(zip(keys, cfg)), 'dev_trades': int(len(dev)),
                       'test_trades_2026': int(len(test26)), 'features': stats_f,
                       'fdr10_survivors': sorted(survivors), 'filters_oos_2026': filters},
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: summary[k] for k in ('walk_forward', 'oos', 'decision_steps_1_2')}, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
