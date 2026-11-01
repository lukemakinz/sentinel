"""S117: entry information test + walk-forward exit-geometry grid for H3B.

Protocol: docs/research/s117_exit_geometry/protocol.json (frozen before results).
    PYTHONPATH=. ../env/bin/python -m backtest.run_s117_exit_geometry
"""
from __future__ import annotations

import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .auction_replay import load_bars

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / 'docs' / 'research' / 'h3b_trend_double_bottom_v1' / 'base'
OUT = ROOT / 'docs' / 'research' / 's117_exit_geometry'
CACHE = os.environ.get('PAPER_FORWARD_CACHE', '/tmp/sentinel-scalp-cache')
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'XRPUSDT', 'ADAUSDT', 'DOGEUSDT',
           'MATICUSDT', 'LINKUSDT', 'BNBUSDT']
DATA = (pd.Timestamp('2023-12-01', tz='UTC'), pd.Timestamp('2026-10-01', tz='UTC'))
BASE_SLIP = 5.0  # slippage used by the H3B base run that produced risk_pct
TAKER, MAKER = 5.0, 2.0
SLIPPAGE = {'base': 5.0, 'stress': 10.0}
STOPS = [0.5, 1.0, 1.5, 2.0]
TARGETS = [1.0, 1.5, 2.0, 3.0, 5.0, None]
HOLDS_H = [24, 72, 168]
HORIZONS_MIN = [60, 240, 1440, 4320]
RANDOM_PER_TRADE = 20
ORIGINAL = (1.0, 2.0, 72)


def simulate_exit(direction: int, entry: float, risk: float, highs: np.ndarray, lows: np.ndarray,
                  closes: np.ndarray, target_r: float | None, hold_bars: int, slip: float) -> float:
    """Net R of one exit configuration; same-bar stop first (resolver convention)."""
    h, l, c = highs[:hold_bars], lows[:hold_bars], closes[:hold_bars]
    if len(c) == 0:
        return float('nan')
    stop = entry - direction * risk
    stop_hits = np.flatnonzero(l <= stop) if direction > 0 else np.flatnonzero(h >= stop)
    first_stop = stop_hits[0] if len(stop_hits) else None
    first_target = None
    if target_r is not None:
        target = entry + direction * target_r * risk
        hits = np.flatnonzero(h >= target) if direction > 0 else np.flatnonzero(l <= target)
        first_target = hits[0] if len(hits) else None
    if first_stop is not None and (first_target is None or first_stop <= first_target):
        exit_price, fee = stop * (1 - direction * slip), TAKER
    elif first_target is not None:
        exit_price, fee = entry + direction * target_r * risk, MAKER
    else:
        exit_price, fee = c[-1] * (1 - direction * slip), TAKER
    gross = direction * (exit_price - entry) / risk
    fees = (entry * TAKER + exit_price * fee) / 10_000 / risk
    return float(gross - fees)


def load_trades() -> pd.DataFrame:
    rows = []
    for symbol in SYMBOLS:
        path = RECORDS / f'records_{symbol}.json'
        if path.exists():
            rows += [r for r in json.loads(path.read_text()) if r.get('risk_pct')]
    df = pd.DataFrame(rows)
    df['armed_at'] = pd.to_datetime(df.armed_at, utc=True)
    df['year'] = df.armed_at.dt.year
    df['day'] = df.armed_at.dt.floor('D')
    return df.reset_index(drop=True)


def evaluate_symbol(trades: pd.DataFrame, symbol: str, rng: np.random.Generator) -> tuple[list, list]:
    bars = load_bars(symbol, '1m', DATA[0], DATA[1], CACHE)
    open_ms, highs, lows, closes = bars.open_ms, bars.h, bars.l, bars.c
    max_hold = max(HOLDS_H) * 60
    grid_rows, info_rows = [], []
    years = pd.to_datetime(open_ms, unit='ms', utc=True).year.to_numpy()
    for i, t in trades[trades.symbol == symbol].iterrows():
        idx = int(np.searchsorted(open_ms, int(t.armed_at.value // 10**6), side='left'))
        if idx >= len(closes):
            continue
        direction = 1 if t.direction == 'LONG' else -1
        raw = closes[idx]
        base_entry = raw * (1 + direction * BASE_SLIP / 10_000)
        risk0 = t.risk_pct / 100 * base_entry
        window = slice(idx + 1, idx + 1 + max_hold)
        h, l, c = highs[window], lows[window], closes[window]
        for scenario, slip_bps in SLIPPAGE.items():
            slip = slip_bps / 10_000
            entry = raw * (1 + direction * slip)
            for k, target, hold in itertools.product(STOPS, TARGETS, HOLDS_H):
                grid_rows.append({
                    'trade': i, 'scenario': scenario, 'stop_k': k, 'target_r': target or 0.0,
                    # Resolver convention: rows with ts < entry + hold -> hold*60 - 1 bars
                    # after the entry bar (verified: 0 mismatches vs the H3B replay).
                    'hold_h': hold, 'net_r': simulate_exit(direction, entry, k * risk0, h, l, c,
                                                           target, hold * 60 - 1, slip)})
        # Part 1: forward signed return in original-risk units vs random entries.
        same_year = np.flatnonzero((years == t.year) & (np.arange(len(closes)) < len(closes) - 4321))
        picks = rng.choice(same_year, size=RANDOM_PER_TRADE, replace=False) if len(same_year) else []
        for horizon in HORIZONS_MIN:
            if idx + horizon >= len(closes):
                continue
            fwd = direction * (closes[idx + horizon] - raw) / (t.risk_pct / 100 * raw)
            rand = [direction * (closes[j + horizon] - closes[j]) / (t.risk_pct / 100 * closes[j])
                    for j in picks]
            info_rows.append({'trade': i, 'horizon_min': horizon, 'h3b': fwd,
                              'random': float(np.mean(rand)) if rand else np.nan})
    return grid_rows, info_rows


def day_bootstrap(values: pd.Series, days: pd.Series, reps: int = 5000, seed: int = 3) -> list[float]:
    frame = pd.DataFrame({'v': values.to_numpy(), 'd': days.to_numpy()}).dropna()
    g = frame.groupby('d').v.agg(['sum', 'count'])
    sums, counts = g['sum'].to_numpy(), g['count'].to_numpy()
    picks = np.random.default_rng(seed).integers(0, len(sums), size=(reps, len(sums)))
    means = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    return [round(float(np.quantile(means, 0.025)), 4), round(float(np.quantile(means, 0.975)), 4)]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    trades = load_trades()
    rng = np.random.default_rng(17)
    grid, info = [], []
    for symbol in SYMBOLS:
        if (trades.symbol == symbol).any():
            g, inf = evaluate_symbol(trades, symbol, rng)
            grid += g
            info += inf
            print(f'{symbol}: done', flush=True)
    grid = pd.DataFrame(grid).merge(trades[['year', 'day']], left_on='trade', right_index=True)
    info = pd.DataFrame(info).merge(trades[['day']], left_on='trade', right_index=True)
    grid.to_csv(OUT / 'grid_trades.csv.gz', index=False)

    # Part 1
    part1 = {}
    for horizon, part in info.groupby('horizon_min'):
        diff = part.h3b - part.random
        part1[str(horizon)] = {'n': int(len(part)), 'h3b_mean_r': round(float(part.h3b.mean()), 4),
                               'random_mean_r': round(float(part.random.mean()), 4),
                               'diff_mean_r': round(float(diff.mean()), 4),
                               'diff_ci95': day_bootstrap(diff, part.day)}
    informative = any(v['diff_ci95'][0] > 0 for v in part1.values())

    # Part 2: walk-forward on stress
    stress = grid[grid.scenario == 'stress']
    keys = ['stop_k', 'target_r', 'hold_h']
    folds, oos = [], []
    for train_years, test_year in (([2024], 2025), ([2024, 2025], 2026)):
        train = stress[stress.year.isin(train_years)].groupby(keys).net_r.mean()
        best = train.idxmax()
        test = stress[(stress.year == test_year)]
        chosen = test.set_index(keys).loc[best].reset_index()
        oos.append(chosen.assign(fold_test_year=test_year))
        folds.append({'train': train_years, 'test': test_year,
                      'chosen': dict(zip(keys, map(float, best))),
                      'train_mean_r': round(float(train.max()), 4),
                      'test_mean_r': round(float(chosen.net_r.mean()), 4),
                      'test_trades': int(len(chosen))})
    oos = pd.concat(oos)
    oos_years = oos.fold_test_year.unique()
    original = stress[(stress.year.isin(oos_years)) & (stress.stop_k == ORIGINAL[0])
                      & (stress.target_r == ORIGINAL[1]) & (stress.hold_h == ORIGINAL[2])]
    per_config_oos = stress[stress.year.isin(oos_years)].groupby(keys).net_r.mean()
    full = stress.groupby(keys).net_r.mean().sort_values(ascending=False)
    lo, hi = day_bootstrap(oos.net_r, oos.day)
    summary = {
        'protocol': 'S117_EXIT_GEOMETRY v1.0.0', 'trades': int(len(trades)),
        'part1_information': part1, 'entries_informative': informative,
        'walk_forward': folds,
        'oos_stress': {'trades': int(len(oos)), 'mean_net_r': round(float(oos.net_r.mean()), 4),
                       'ci95': [lo, hi], 'total_r': round(float(oos.net_r.sum()), 1)},
        'oos_original_geometry_mean_r': round(float(original.net_r.mean()), 4),
        'oos_median_config_mean_r': round(float(per_config_oos.median()), 4),
        'upper_bound_in_sample_top5': [
            {**dict(zip(keys, map(float, k))), 'mean_net_r': round(float(v), 4)}
            for k, v in full.head(5).items()],
        'share_of_configs_positive_in_sample': round(float((full > 0).mean()), 3),
    }
    summary['decision'] = ('PASS_TO_NEW_PROTOCOL' if informative and lo > 0 else 'REJECTED')
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
