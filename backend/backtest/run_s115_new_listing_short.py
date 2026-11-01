"""S115: short new Binance USD-M perpetual listings (frozen protocol).

Protocol: docs/research/s115_new_listing_short/protocol.json (frozen before
results).  Usage:
    PYTHONPATH=. ../env/bin/python -m backtest.run_s115_new_listing_short
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .broad_universe import BUCKET, INDEX_SYMBOLS, NON_ALT_BASES, daily_klines, list_usdt_perpetuals
from .scalp_data import archive

OUT = Path(__file__).resolve().parents[2] / 'docs' / 'research' / 's115_new_listing_short'
CACHE = os.environ.get('PAPER_FORWARD_CACHE', '/tmp/sentinel-scalp-cache')
WINDOW = (pd.Timestamp('2023-01-01', tz='UTC'), pd.Timestamp('2026-08-01', tz='UTC'))
FEE_BPS = 5.0
SLIPPAGE_BPS = {'base': 10.0, 'stress': 30.0}
HEDGE_COST = 2 * (FEE_BPS + 2.0) / 10_000  # BTC leg round trip, liquid
NOTIONAL_USD = 25.0
HYPOTHESES = {
    'S115_A': {'entry_index': 1, 'hold_days': 14, 'stop_pct': 0.35},
    'S115_B': {'entry_index': 3, 'hold_days': 30, 'stop_pct': 0.50},
}
DAY = pd.Timedelta(days=1)


# ------------------------------------------------------------------ simulation
def simulate_short(bars: pd.DataFrame, funding: pd.Series, *, entry_index: int,
                   hold_days: int, stop_pct: float, slippage_bps: float,
                   fee_bps: float = FEE_BPS) -> dict | None:
    """One short trade on daily bars (index = UTC day open).  Causal: entry at
    a bar open, stop on that bar's or later highs, exit at a later close."""
    if len(bars) <= entry_index:
        return None
    slip = slippage_bps / 10_000
    raw_entry = float(bars.open.iloc[entry_index])
    entry_time = bars.index[entry_index]
    stop_price = raw_entry * (1 + stop_pct)
    planned_last = entry_index + hold_days - 1
    last = min(planned_last, len(bars) - 1)
    reason, raw_exit, exit_bar = 'TIME', float(bars.close.iloc[last]), last
    for i in range(entry_index, last + 1):
        if float(bars.high.iloc[i]) >= stop_price:
            reason = 'STOP'
            raw_exit = max(stop_price, float(bars.open.iloc[i]))  # gap fills worse
            exit_bar = i
            break
    else:
        if last < planned_last:
            reason = 'DATA_END'
    exit_time = bars.index[exit_bar] + DAY  # conservative: funding to day end
    entry = raw_entry * (1 - slip)   # selling: adverse = lower
    exit_ = raw_exit * (1 + slip)    # buying back: adverse = higher
    gross = (entry - exit_) / raw_entry
    if funding.empty:
        funding_sum = 0.0
    else:
        window = funding[(funding.index >= entry_time) & (funding.index < exit_time)]
        funding_sum = float(window.sum())  # short receives positive funding
    net = gross - 2 * fee_bps / 10_000 + funding_sum
    return {
        'entry_time': entry_time, 'exit_time': exit_time, 'reason': reason,
        'raw_entry': raw_entry, 'raw_exit': raw_exit, 'gross': gross,
        'funding': funding_sum, 'net': net, 'days_held': exit_bar - entry_index + 1,
    }


# ------------------------------------------------------------------------ data
def first_month(symbol: str, session: requests.Session) -> str | None:
    text = session.get(BUCKET, params={
        'prefix': f'data/futures/um/monthly/klines/{symbol}/1d/', 'delimiter': '/'},
        timeout=30).text
    months = re.findall(rf'{symbol}-1d-(\d{{4}}-\d{{2}})\.zip<', text)
    return min(months) if months else None


def load_daily(symbol: str, months: list[str]) -> pd.DataFrame | None:
    frames = [f for f in (daily_klines(symbol, m, CACHE) for m in months) if f is not None]
    if not frames:
        return None
    df = pd.concat(frames)
    df = df[~df.index.duplicated()].sort_index()
    return df[['open', 'high', 'low', 'close', 'quote_volume']].astype(float)


def load_funding(symbol: str, months: list[str]) -> pd.Series:
    parts = []
    for month in months:
        try:
            raw, _ = archive(symbol, month, 'fundingRate', CACHE)
        except requests.HTTPError:
            continue
        index = pd.to_datetime(raw.calc_time, unit='ms', utc=True).dt.floor('min')
        parts.append(pd.Series(raw.last_funding_rate.astype(float).to_numpy(), index=index))
    if not parts:
        return pd.Series(dtype=float)
    series = pd.concat(parts).sort_index()
    return series[~series.index.duplicated()]


def months_from(start: str, count: int) -> list[str]:
    first = pd.Period(start, freq='M')
    return [str(first + i) for i in range(count)]


def discover_listings() -> list[dict]:
    session = requests.Session()
    candidates = [s for s in list_usdt_perpetuals()
                  if s not in {'BTCUSDT', 'ETHUSDT'} and s not in INDEX_SYMBOLS
                  and s[:-4] not in NON_ALT_BASES]

    def probe(symbol):
        month = first_month(symbol, session)
        if month is None or not (str(WINDOW[0].to_period('M'))[:7] <= month
                                 <= str((WINDOW[1] - DAY).tz_localize(None).to_period('M'))):
            return None
        months = months_from(month, 3)
        bars = load_daily(symbol, months)
        if bars is None or bars.index[0] < WINDOW[0] or bars.index[0] >= WINDOW[1]:
            return None
        return {'symbol': symbol, 'listing': bars.index[0], 'months': months}

    with ThreadPoolExecutor(max_workers=12) as pool:
        return sorted((x for x in pool.map(probe, candidates) if x),
                      key=lambda x: x['listing'])


# ---------------------------------------------------------------------- stats
def month_block_lower(df: pd.DataFrame, column: str, q: float = 0.025,
                      reps: int = 5000, seed: int = 11) -> tuple[float, float]:
    grouped = df.groupby(df.listing.dt.to_period('M'))[column].agg(['sum', 'count'])
    sums, counts = grouped['sum'].to_numpy(), grouped['count'].to_numpy()
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(sums), size=(reps, len(sums)))
    means = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    return float(np.quantile(means, q)), float(np.quantile(means, 1 - q))


def max_concurrency(df: pd.DataFrame) -> int:
    events = sorted([(t, 1) for t in df.entry_time] + [(t, -1) for t in df.exit_time],
                    key=lambda e: (e[0], e[1]))
    level = peak = 0
    for _, step in events:
        level += step
        peak = max(peak, level)
    return peak


def evaluate(trades: pd.DataFrame, days: float) -> dict:
    out = {}
    for scenario in ('base', 'stress'):
        part = trades[trades.scenario == scenario]
        lo, hi = month_block_lower(part, 'net')
        out[scenario] = {
            'trades': int(len(part)),
            'mean_net_pct': round(part.net.mean() * 100, 3),
            'median_net_pct': round(part.net.median() * 100, 3),
            'win_rate': round(float((part.net > 0).mean()), 3),
            'ci97_5_pct': [round(lo * 100, 3), round(hi * 100, 3)],
            'mean_funding_pct': round(part.funding.mean() * 100, 3),
            'stop_rate': round(float(part.reason.eq('STOP').mean()), 3),
            'hedged_mean_net_pct': round(part.hedged.mean() * 100, 3),
            'by_year_mean_net_pct': {
                str(y): round(g.net.mean() * 100, 3)
                for y, g in part.groupby(part.listing.dt.year)},
            'by_year_trades': {str(y): int(len(g)) for y, g in part.groupby(part.listing.dt.year)},
            'usd_total_at_25': round(part.net.sum() * NOTIONAL_USD, 2),
            'usd_per_day_at_25': round(part.net.sum() * NOTIONAL_USD / days, 3),
            'max_concurrent': max_concurrency(part),
            'worst_trade_pct': round(part.net.min() * 100, 2),
            'trades_without_funding_data': int((part.funding_points == 0).sum()),
        }
    s = out['stress']
    gates = {
        'ci_lower_above_zero': s['ci97_5_pct'][0] > 0,
        'every_year_positive': all(v > 0 for k, v in s['by_year_mean_net_pct'].items()
                                   if k in {'2023', '2024', '2025', '2026'})
        and {'2023', '2024', '2025', '2026'} <= set(s['by_year_mean_net_pct']),
        'btc_hedged_positive': s['hedged_mean_net_pct'] > 0,
    }
    out['gates'] = gates
    out['decision'] = 'PASS_TO_FORWARD' if all(gates.values()) else 'REJECTED'
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    listings = discover_listings()
    print(f'listings in window: {len(listings)}', flush=True)
    btc = load_daily('BTCUSDT', months_from('2023-01', 46))
    rows = []
    for item in listings:
        bars = load_daily(item['symbol'], item['months'])
        funding = load_funding(item['symbol'], item['months'])
        for hid, params in HYPOTHESES.items():
            for scenario, slip in SLIPPAGE_BPS.items():
                trade = simulate_short(bars, funding, slippage_bps=slip, **params)
                if trade is None:
                    continue
                entry_day, exit_day = trade['entry_time'], trade['exit_time'] - DAY
                try:
                    btc_ret = float(btc.close.loc[exit_day] / btc.open.loc[entry_day] - 1)
                except KeyError:
                    btc_ret = np.nan
                rows.append({
                    'symbol': item['symbol'], 'listing': item['listing'], 'hypothesis': hid,
                    'scenario': scenario, **trade,
                    'btc_return': btc_ret, 'hedged': trade['net'] + btc_ret - HEDGE_COST,
                    'funding_points': int(len(funding)),
                })
    trades = pd.DataFrame(rows)
    trades.to_csv(OUT / 'trades.csv', index=False)
    days = (WINDOW[1] - WINDOW[0]).days
    summary = {'protocol': 'S115_NEW_LISTING_SHORT v1.0.0', 'listings': len(listings),
               'window': [str(WINDOW[0].date()), str(WINDOW[1].date())], 'days': days}
    for hid in HYPOTHESES:
        summary[hid] = evaluate(trades[trades.hypothesis == hid], days)
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
