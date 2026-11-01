"""S116 regime atlas + router (frozen protocol docs/research/s116_regime_atlas).

    PYTHONPATH=. ../env/bin/python -m backtest.run_s116_regime_atlas
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .broad_universe import daily_klines
from .scalp_data import archive

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs' / 'research' / 's116_regime_atlas'
S115_TRADES = ROOT / 'docs' / 'research' / 's115_new_listing_short' / 'trades.csv'
CACHE = os.environ.get('PAPER_FORWARD_CACHE', '/tmp/sentinel-scalp-cache')
DEV = (pd.Timestamp('2023-01-01', tz='UTC'), pd.Timestamp('2025-01-01', tz='UTC'))
HOLD = (pd.Timestamp('2025-01-01', tz='UTC'), pd.Timestamp('2026-09-01', tz='UTC'))  # contaminated diagnostic
DATA_START = pd.Timestamp('2022-05-01', tz='UTC')  # 200d SMA warmup before DEV
BOOK = 250.0
DAY = pd.Timedelta(days=1)
DAILY_STREAMS = ('BOOK_A', 'BOOK_B', 'BTC_SMA200_LONG')
TRADE_STREAMS = ('S115_A',)  # one pre-registered variant (v1.1)
VOL_TARGET, VOL_LOOKBACK, BRAKE_DD = 0.10, 60, 0.10
PORTFOLIO = 500.0
SLEEVE = PORTFOLIO / 4          # BOOK_A, BOOK_B, BTC_SMA200_LONG, S115_A
S115_NOTIONAL, S115_MAX_OPEN = 25.0, 5
MIN_DAYS, MIN_TRADES, MIN_T = 100, 50, 2.9


# ------------------------------------------------------------------ regimes
def classify_regimes(close: pd.Series) -> pd.DataFrame:
    """Regime for day d (open-indexed) from closes of days <= d-1 only."""
    sma100 = close.rolling(100).mean()
    up = (close > sma100) & (sma100 > sma100.shift(20))
    down = (close < sma100) & (sma100 < sma100.shift(20))
    trend = pd.Series(np.where(up, 'UP', np.where(down, 'DOWN', 'SIDEWAYS')), index=close.index)
    trend[sma100.shift(20).isna()] = None
    vol = np.log(close).diff().rolling(20).std() * math.sqrt(365)
    median = vol.rolling(365, min_periods=365).median()
    level = pd.Series(np.where(vol > median, 'HIGH', 'LOW'), index=close.index)
    level[median.isna()] = None
    frame = pd.DataFrame({'trend': trend, 'vol': level}).shift(1)  # causal
    frame['cell'] = frame.trend + '_' + frame.vol
    frame.loc[frame.trend.isna() | frame.vol.isna(), 'cell'] = None
    return frame


# ------------------------------------------------------------------ streams
def daily_bars(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    months = pd.period_range(start.tz_localize(None), (end - DAY).tz_localize(None), freq='M')
    frames = [f for f in (daily_klines(symbol, str(m), CACHE) for m in months) if f is not None]
    df = pd.concat(frames)
    return df[~df.index.duplicated()].sort_index()[['open', 'high', 'low', 'close']].astype(float)


def funding_series(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    parts = []
    for m in pd.period_range(start.tz_localize(None), (end - DAY).tz_localize(None), freq='M'):
        try:
            raw, _ = archive(symbol, str(m), 'fundingRate', CACHE)
        except requests.HTTPError:
            continue
        idx = pd.to_datetime(raw.calc_time, unit='ms', utc=True).dt.floor('min')
        parts.append(pd.Series(raw.last_funding_rate.astype(float).to_numpy(), index=idx))
    s = pd.concat(parts).sort_index()
    return s[~s.index.duplicated()]


def btc_sma200_stream(bars: pd.DataFrame, funding: pd.Series, cost_bps: float = 12.0) -> pd.Series:
    """Daily $ PnL on $250: long from day d iff close[d-1] > SMA200[d-1]."""
    close = bars.close
    position = (close > close.rolling(200).mean()).astype(float).shift(1).fillna(0.0)
    ret = close / close.shift(1) - 1
    switches = position.diff().abs().fillna(position)
    day_funding = funding.groupby(funding.index.floor('D')).sum().reindex(close.index).fillna(0.0)
    pnl = BOOK * (position * ret.fillna(0.0) - switches * cost_bps / 10_000
                  - position * day_funding)
    return pnl


def book_ab_streams() -> tuple[pd.Series, pd.Series]:
    """Frozen Book A / Book B daily $ PnL (stress), re-indexed to day-open."""
    from .bench_ab_r2_replay import book_b_signals, replay
    from .run_bench_ab_r2 import SYMBOLS
    minutes, funding = {}, {}
    for symbol in SYMBOLS:
        minutes[symbol], funding[symbol] = load_minutes_repaired(symbol)
        print(f'  loaded {symbol}', flush=True)
    result = replay(minutes, funding, book_b_signals(minutes), DEV[0], HOLD[1], 'stress')
    a = result['daily_a'].copy()
    a.index = pd.DatetimeIndex(a.index).tz_convert('UTC') - DAY  # label='right' -> day open
    b = result['daily_b'].copy()
    b.index = pd.DatetimeIndex([pd.Timestamp(t).tz_localize('UTC') if pd.Timestamp(t).tzinfo is None
                                else pd.Timestamp(t) for t in b.index]).normalize()
    return a.sort_index(), b.sort_index()


DATA_REPAIRS: list[dict] = []


def load_minutes_repaired(symbol: str) -> tuple[pd.DataFrame, pd.Series]:
    """Monthly 1m archives + funding with one documented repair.

    Binance archives contain rare rows whose ``volume`` is corrupted (e.g.
    XRPUSDT 2023-11-30 12:35: taker_buy 132,462 > volume 91,696 while
    quote_volume implies ~331,800).  Such rows get ``volume = quote_volume /
    close`` (never below taker_buy); every repair is recorded in the summary.
    """
    from .scalp_data import COLUMNS, _daily_kline_archive, _repair_missing_minutes, validate_minutes

    candles, rates = [], []
    for month in pd.period_range(DATA_START.tz_localize(None), (HOLD[1] - DAY).tz_localize(None), freq='M'):
        raw, _ = archive(symbol, str(month), 'klines', CACHE)
        if not str(raw.iloc[0, 0]).isdigit():
            raw = raw.iloc[1:]
        raw = raw.iloc[:, :len(COLUMNS)]
        raw.columns = COLUMNS
        raw.index = pd.to_datetime(raw.timestamp.astype('int64'), unit='ms', utc=True)
        frame = raw[['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume', 'quote_volume']].astype(float)
        bad = frame.taker_buy_volume > frame.volume + 1e-8
        for ts, row in frame[bad].iterrows():
            fixed = max(row.quote_volume / row.close, row.taker_buy_volume)
            DATA_REPAIRS.append({'symbol': symbol, 'time': str(ts), 'volume': row.volume,
                                 'taker_buy_volume': row.taker_buy_volume, 'repaired_volume': fixed})
            frame.loc[ts, 'volume'] = fixed
        candles.append(frame.drop(columns='quote_volume'))
        try:
            f, _ = archive(symbol, str(month), 'fundingRate', CACHE)
            idx = pd.to_datetime(f.calc_time, unit='ms', utc=True).dt.floor('min')
            rates.append(pd.Series(f.last_funding_rate.astype(float).to_numpy(), index=idx))
        except requests.HTTPError:
            pass
    minutes = pd.concat(candles).sort_index()
    minutes = minutes[~minutes.index.duplicated()]
    minutes = minutes[(minutes.index >= DATA_START) & (minutes.index < HOLD[1])]
    minutes, _ = _repair_missing_minutes(minutes, DATA_START, HOLD[1],
                                         lambda day: _daily_kline_archive(symbol, day, CACHE))
    validate_minutes(minutes)
    funding = pd.concat(rates).sort_index()
    return minutes, funding[~funding.index.duplicated()]


def trade_streams() -> dict[str, pd.DataFrame]:
    if not S115_TRADES.exists():
        return {}
    t = pd.read_csv(S115_TRADES, parse_dates=['entry_time', 'exit_time'])
    t = t[t.scenario == 'stress']
    return {h: g.assign(pnl=g.net * S115_NOTIONAL).sort_values('entry_time')
            for h, g in t.groupby('hypothesis') if h in TRADE_STREAMS}


# ---------------------------------------------------------------- risk layer
def vol_scale(pnl: pd.Series) -> pd.Series:
    r = pnl / BOOK
    realized = r.rolling(VOL_LOOKBACK).std().shift(1) * math.sqrt(365)
    return (VOL_TARGET / realized).clip(upper=1.0).fillna(0.0)


def apply_brake(daily: pd.Series) -> pd.Series:
    out, equity, peak = [], 0.0, 0.0
    capital = PORTFOLIO
    for value in daily:
        factor = 0.5 if (capital + equity) < (capital + peak) * (1 - BRAKE_DD) else 1.0
        realized = value * factor
        out.append(realized)
        equity += realized
        peak = max(peak, equity)
    return pd.Series(out, index=daily.index)


# -------------------------------------------------------------------- atlas
def weekly_t(values: pd.Series) -> float:
    weekly = values.groupby(values.index.to_period('W')).sum()
    if len(weekly) < 3 or weekly.std() == 0:
        return 0.0
    return float(weekly.mean() / weekly.std() * math.sqrt(len(weekly)))


def atlas(daily: dict[str, pd.Series], trades: dict[str, pd.DataFrame],
          regimes: pd.DataFrame, window) -> dict:
    out = {}
    cells = sorted(regimes.cell.dropna().unique())
    for name, pnl in daily.items():
        frame = pd.DataFrame({'pnl': pnl}).join(regimes.cell)
        frame = frame[(frame.index >= window[0]) & (frame.index < window[1])]
        out[name] = {}
        for cell in cells:
            part = frame[frame.cell == cell].pnl
            out[name][cell] = {'n': int(len(part)), 'mean': round(float(part.mean()), 4) if len(part) else None,
                               'total': round(float(part.sum()), 2), 't': round(weekly_t(part), 2),
                               'year_means': {str(y): round(float(g.mean()), 4)
                                              for y, g in part.groupby(part.index.year)},
                               'top_month_share': _top_month_share(part)}
    for name, t in trades.items():
        t = t.assign(cell=regimes.cell.reindex(t.entry_time.dt.floor('D')).to_numpy())
        t = t[(t.entry_time >= window[0]) & (t.entry_time < window[1])]
        out[name] = {}
        for cell in cells:
            part = t[t.cell == cell].pnl
            tstat = (float(part.mean() / part.std() * math.sqrt(len(part)))
                     if len(part) > 2 and part.std() > 0 else 0.0)
            out[name][cell] = {'n': int(len(part)), 'mean': round(float(part.mean()), 4) if len(part) else None,
                               'total': round(float(part.sum()), 2), 't': round(tstat, 2),
                               'year_means': {str(y): round(float(g.mean()), 4) for y, g in
                                              part.groupby(t.loc[part.index, 'entry_time'].dt.year)}}
    return out


def _top_month_share(part: pd.Series) -> float | None:
    monthly = part.groupby(part.index.to_period('M')).sum()
    positive = monthly[monthly > 0]
    return round(float(positive.max() / positive.sum()), 3) if len(positive) else None


def router_map(dev_atlas: dict, years=('2023', '2024')) -> dict[str, list[str]]:
    """v1.1: size, mean, Bonferroni-strength t and positivity in every dev year."""
    enabled = {}
    for name, cells in dev_atlas.items():
        minimum = MIN_TRADES if name in TRADE_STREAMS else MIN_DAYS
        enabled[name] = sorted(
            c for c, s in cells.items()
            if s['n'] >= minimum and (s['mean'] or 0) > 0 and s['t'] >= MIN_T
            and all((s.get('year_means') or {}).get(y, -1) > 0 for y in years))
    return enabled


def portfolio(daily: dict[str, pd.Series], trades: dict[str, pd.DataFrame], regimes: pd.DataFrame,
              enabled: dict[str, list[str]] | None, window) -> pd.Series:
    """Daily $ PnL; enabled=None means always-on."""
    index = pd.date_range(window[0], window[1] - DAY, freq='D', tz='UTC')
    cell = regimes.cell.reindex(index)
    total = pd.Series(0.0, index=index)
    for name, pnl in daily.items():
        # Streams are simulated on $250; each owns a $125 sleeve of the $500 portfolio.
        scaled = (pnl * (SLEEVE / BOOK) * vol_scale(pnl)).reindex(index).fillna(0.0)
        if enabled is not None:
            scaled = scaled.where(cell.isin(enabled.get(name, [])), 0.0)
        total += scaled
    for name, t in trades.items():
        entry_cell = regimes.cell.reindex(t.entry_time.dt.floor('D')).to_numpy()
        keep = t if enabled is None else t[np.isin(entry_cell, enabled.get(name, []))]
        keep = keep[(keep.entry_time >= window[0]) & (keep.entry_time < window[1])]
        keep = cap_concurrency(keep, S115_MAX_OPEN)
        by_exit = keep.groupby((keep.exit_time - DAY).dt.floor('D')).pnl.sum()
        total = total.add(by_exit.reindex(index).fillna(0.0), fill_value=0.0)
    return apply_brake(total)


def cap_concurrency(trades: pd.DataFrame, max_open: int) -> pd.DataFrame:
    """Skip a new trade while ``max_open`` earlier trades are still open."""
    kept, open_exits = [], []
    for idx, row in trades.sort_values('entry_time').iterrows():
        open_exits = [e for e in open_exits if e > row.entry_time]
        if len(open_exits) >= max_open:
            continue
        open_exits.append(row.exit_time)
        kept.append(idx)
    return trades.loc[kept]


def month_block_lower(daily: pd.Series, reps: int = 5000, seed: int = 5) -> float:
    groups = daily.groupby(daily.index.to_period('M'))
    sums = groups.sum().to_numpy()
    counts = groups.count().to_numpy()
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(sums), size=(reps, len(sums)))
    return float(np.quantile(sums[picks].sum(axis=1) / counts[picks].sum(axis=1), 0.05))


def stats(daily: pd.Series) -> dict:
    equity = daily.cumsum()
    sharpe = daily.mean() / daily.std() * math.sqrt(365) if daily.std() > 0 else 0.0
    return {'total_usd': round(float(daily.sum()), 2), 'usd_per_day': round(float(daily.mean()), 3),
            'sharpe': round(float(sharpe), 2),
            'max_dd_usd': round(float((equity - equity.cummax()).min()), 2),
            'month_block_lower95_usd_per_day': round(month_block_lower(daily), 4)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    btc = daily_bars('BTCUSDT', DATA_START - pd.Timedelta(days=400), HOLD[1])
    regimes = classify_regimes(btc.close)
    regimes.to_csv(OUT / 'regimes.csv')
    print('regimes ready', flush=True)
    daily = {'BTC_SMA200_LONG': btc_sma200_stream(btc, funding_series('BTCUSDT', DATA_START, HOLD[1]))}
    a, b = book_ab_streams()
    daily['BOOK_A'], daily['BOOK_B'] = a, b
    trades = trade_streams()
    pd.DataFrame(daily).to_csv(OUT / 'daily_streams.csv')

    dev_atlas = atlas(daily, trades, regimes, DEV)
    hold_atlas = atlas(daily, trades, regimes, HOLD)
    enabled = router_map(dev_atlas)
    router = portfolio(daily, trades, regimes, enabled, HOLD)
    always = portfolio(daily, trades, regimes, None, HOLD)
    router_dev = portfolio(daily, trades, regimes, enabled, DEV)
    always_dev = portfolio(daily, trades, regimes, None, DEV)
    gates = {
        'router_diagnostic_positive': router.sum() > 0,
        'router_beats_always_on': router.sum() > always.sum(),
        'router_bootstrap_lower_above_zero': month_block_lower(router) > 0,
    }
    summary = {
        'protocol': 'S116_REGIME_ATLAS v1.1.0',
        'cell_days': {'development': regimes.cell[(regimes.index >= DEV[0]) & (regimes.index < DEV[1])]
                      .value_counts().to_dict(),
                      'diagnostic_2025_2026': regimes.cell[(regimes.index >= HOLD[0]) & (regimes.index < HOLD[1])]
                      .value_counts().to_dict()},
        'router_map': enabled,
        'atlas_development': dev_atlas, 'atlas_diagnostic_2025_2026': hold_atlas,
        'diagnostic_2025_2026': {'router': stats(router), 'always_on': stats(always)},
        'development_in_sample': {'router': stats(router_dev), 'always_on': stats(always_dev)},
        'gates': {k: bool(v) for k, v in gates.items()},
        'decision': 'PASS_TO_PAPER_FORWARD' if all(gates.values()) else 'REJECTED',
        'capital': {'portfolio_usd': PORTFOLIO, 'sleeve_usd': SLEEVE},
        'data_repairs': DATA_REPAIRS,
        'streams_included': sorted([*daily, *trades]),
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: summary[k] for k in ('router_map', 'diagnostic_2025_2026', 'gates', 'decision')},
                     indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
