"""S119: frozen Book A on a point-in-time universe vs its hindsight 5-coin universe.

Protocol: docs/research/s119_book_a_pit_universe/protocol.json (frozen).
    PYTHONPATH=. ../env/bin/python -m backtest.run_s119_book_a_pit
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM, BookASmallTsmomConfig
from .book_a_portfolio_sim import simulate_book_a
from .broad_universe import daily_klines

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs' / 'research' / 's119_book_a_pit_universe'
BREADTH = ROOT / 'docs' / 'research' / 'auction_replay_v1' / 'breadth_by_quarter.json'
CACHE = os.environ.get('PAPER_FORWARD_CACHE', '/tmp/sentinel-scalp-cache')
PERIOD = (pd.Timestamp('2024-01-01', tz='UTC'), pd.Timestamp('2026-10-01', tz='UTC'))
PANEL_START = '2023-03'
COSTS = {'base': 7.0, 'stress': 12.0}
CAPITAL = 250.0


@dataclass(frozen=True)
class PITBookAConfig(BookASmallTsmomConfig):
    universe: tuple[str, ...] = ()

    def alt_symbols(self) -> tuple[str, ...]:
        return self.universe


def build_panel(symbols: list[str]) -> pd.DataFrame:
    """Daily closes indexed at end of day (the simulator's label='right' convention)."""
    months = [str(m) for m in pd.period_range(PANEL_START, '2026-09', freq='M')]
    series = {}
    for symbol in symbols:
        frames = [f for f in (daily_klines(symbol, m, CACHE) for m in months) if f is not None]
        if not frames:
            continue
        df = pd.concat(frames)
        df = df[~df.index.duplicated()].sort_index()
        close = df.close.astype(float)
        close.index = close.index + pd.Timedelta(days=1)
        series[symbol] = close
    return pd.DataFrame(series).sort_index().ffill()


def month_block_lower(daily: pd.Series, reps: int = 5000, seed: int = 9) -> float:
    g = daily.groupby(daily.index.to_period('M'))
    sums, counts = g.sum().to_numpy(), g.count().to_numpy()
    picks = np.random.default_rng(seed).integers(0, len(sums), size=(reps, len(sums)))
    return float(np.quantile(sums[picks].sum(axis=1) / counts[picks].sum(axis=1), 0.05))


def stats(result) -> dict:
    daily = result.daily_pnl.copy()
    daily.index = pd.DatetimeIndex(daily.index)
    equity = daily.cumsum()
    sharpe = daily.mean() / daily.std() * math.sqrt(365) if daily.std() > 0 else 0.0
    return {
        'total_usd': round(float(daily.sum()), 2),
        'usd_per_day': round(float(daily.mean()), 4),
        'return_pct': round(float(daily.sum()) / CAPITAL * 100, 2),
        'sharpe': round(float(sharpe), 2),
        'max_dd_usd': round(float((equity - equity.cummax()).min()), 2),
        'by_year_usd': {str(y): round(float(g.sum()), 2) for y, g in daily.groupby(daily.index.year)},
        'month_block_lower95_usd_per_day': round(month_block_lower(daily), 4),
        'positive_months_share': round(float((daily.groupby(daily.index.to_period('M')).sum() > 0).mean()), 3),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    breadth = json.loads(BREADTH.read_text())
    pit_symbols = sorted({s for lst in breadth.values() for s in lst})
    fixed = list(BOOK_A_ALT_RM.alt_symbols())
    panel = build_panel(sorted({'BTCUSDT', 'ETHUSDT', *pit_symbols, *fixed}))
    print(f'panel {panel.shape}', flush=True)

    def config_for_day_factory(base):
        cache = {}

        def config_for_day(day):
            quarter = str(pd.Timestamp(day).tz_convert('UTC').tz_localize(None).to_period('Q'))
            if quarter not in cache:
                universe = ('ETHUSDT', *[s for s in breadth.get(quarter, []) if s != 'ETHUSDT'])
                cache[quarter] = PITBookAConfig(**{**base.__dict__, 'name': 'BOOK_A_PIT20',
                                                   'universe': universe})
            return cache[quarter]
        return config_for_day

    summary = {'protocol': 'S119_BOOK_A_PIT_UNIVERSE v1.0.0',
               'pit_symbols_ever': pit_symbols, 'fixed_universe': fixed}
    for scenario, fee in COSTS.items():
        base_cfg = replace(BOOK_A_ALT_RM, taker_fee_bps=fee)
        fixed_res = simulate_book_a({}, base_cfg, PERIOD[0], PERIOD[1], CAPITAL,
                                    risk=BOOK_A_RISK_DEFAULT, panel=panel)
        pit_res = simulate_book_a({}, base_cfg, PERIOD[0], PERIOD[1], CAPITAL,
                                  risk=BOOK_A_RISK_DEFAULT, panel=panel,
                                  config_for_day=config_for_day_factory(base_cfg))
        summary[scenario] = {'fixed_5_hindsight': stats(fixed_res), 'pit_20': stats(pit_res)}
        print(scenario, json.dumps(summary[scenario], indent=1), flush=True)
    s = summary['stress']['pit_20']
    gates = {
        'total_positive': s['total_usd'] > 0,
        'bootstrap_lower_above_zero': s['month_block_lower95_usd_per_day'] > 0,
        'every_year_positive': all(s['by_year_usd'].get(y, -1) > 0 for y in ('2024', '2025', '2026')),
    }
    summary['gates'] = gates
    summary['decision'] = 'PASS' if all(gates.values()) else 'REJECTED'
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({'gates': gates, 'decision': summary['decision']}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
