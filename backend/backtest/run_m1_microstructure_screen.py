"""M1 -- microstructure predictiveness screen. NOT a strategy backtest.
Question only: does trailing order-flow state predict the FUTURE trade
price beyond a round-trip cost, with a stable sign across days and
symbols? Built from aggTrades only (see download_agg_trades.py) --
bookTicker (spread/microprice/top-1 imbalance) is deliberately deferred:
it is monthly-only and multi-gigabyte per symbol (1.9-4.5GB for BTCUSDT
alone), a real download commitment not worth making before aggTrades-
based features show anything. True L2 depth beyond top-1 (top-5/10
imbalance, one-side depletion) has NO historical archive on Binance's
public data source at all -- only live via WebSocket, so those specific
features from the user's list cannot be screened historically and are
out of scope for this script entirely.

Pipeline (exactly the order specified, no strategy/execution layer yet):
    feature state (trailing order-flow imbalance, trade tempo)
        -> future trade-price return, several horizons
        -> is the decile spread bigger than an assumed round-trip cost
        -> is the sign the same across days and symbols

Two features (matching the H1/H2 intuition from the brief, without yet
turning them into trade rules):
    imbalance_5s = (aggressive buy volume - aggressive sell volume)
                   / (aggressive buy volume + aggressive sell volume)
                   over the trailing 5 seconds
    tempo_5s     = number of trades in the trailing 5 seconds

Both are built on a uniform 1-second grid (last trade price per second,
forward-filled for silent seconds) so forward returns at fixed horizons
are well-defined without irregular-spacing artifacts.
"""
from itertools import product

import numpy as np
import pandas as pd

from .download_agg_trades import load_agg_trades_day

TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
DAYS = ['2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10',
        '2026-09-11', '2026-09-12', '2026-09-13']
HORIZONS_S = (3, 10, 30, 60)
IMBALANCE_WINDOW_S = 5
TEMPO_WINDOW_S = 5

# Round-trip cost assumptions, in bps, matching this project's own
# base/stress tiers elsewhere (2x one-way: enter + exit).
ROUND_TRIP_BPS = {'base': (5 + 2) * 2, 'stress': (8 + 5) * 2}


def build_one_second_grid(trades: pd.DataFrame) -> pd.DataFrame:
    signed_qty = np.where(trades.is_buyer_maker, -trades.quantity, trades.quantity)
    trades = trades.assign(signed_qty=signed_qty, buy_qty=np.where(signed_qty > 0, trades.quantity, 0.0),
                            sell_qty=np.where(signed_qty < 0, trades.quantity, 0.0))
    grid = trades.resample('1s').agg(
        price=('price', 'last'), trades_n=('price', 'size'),
        buy_qty=('buy_qty', 'sum'), sell_qty=('sell_qty', 'sum'),
    )
    grid['price'] = grid['price'].ffill()
    return grid.dropna(subset=['price'])


def compute_features_and_forward_returns(grid: pd.DataFrame) -> pd.DataFrame:
    buy_roll = grid.buy_qty.rolling(IMBALANCE_WINDOW_S, min_periods=IMBALANCE_WINDOW_S).sum()
    sell_roll = grid.sell_qty.rolling(IMBALANCE_WINDOW_S, min_periods=IMBALANCE_WINDOW_S).sum()
    total = buy_roll + sell_roll
    grid['imbalance_5s'] = ((buy_roll - sell_roll) / total.where(total > 0))
    grid['tempo_5s'] = grid.trades_n.rolling(TEMPO_WINDOW_S, min_periods=TEMPO_WINDOW_S).sum()

    price = grid.price.to_numpy()
    for h in HORIZONS_S:
        future = np.r_[price[h:], np.full(h, np.nan)]
        grid[f'fwd_ret_bps_{h}s'] = (future / price - 1.0) * 10_000
    return grid


def decile_spread(df: pd.DataFrame, feature: str, target: str) -> float:
    """Mean forward return (bps) in the top decile of `feature` minus the
    bottom decile -- the predictive spread this feature offers, in the
    same units as trading cost."""
    valid = df[[feature, target]].dropna()
    if len(valid) < 100:
        return np.nan
    deciles = pd.qcut(valid[feature], 10, labels=False, duplicates='drop')
    if deciles.max() is None or deciles.nunique() < 10:
        return np.nan
    top = valid.loc[deciles == deciles.max(), target].mean()
    bottom = valid.loc[deciles == deciles.min(), target].mean()
    return top - bottom


def main():
    cache = '/tmp/sentinel-tick-cache'
    rows = []
    for symbol, day in product(TRADED, DAYS):
        trades = load_agg_trades_day(symbol, day, cache)
        grid = build_one_second_grid(trades)
        grid = compute_features_and_forward_returns(grid)
        for h in HORIZONS_S:
            target = f'fwd_ret_bps_{h}s'
            row = {
                'symbol': symbol, 'day': day, 'horizon_s': h,
                'n_seconds': len(grid),
                'imbalance_spread_bps': decile_spread(grid, 'imbalance_5s', target),
                'tempo_spread_bps': decile_spread(grid, 'tempo_5s', target),
            }
            rows.append(row)
        print(symbol, day, 'processed', len(trades), 'trades ->', len(grid), 'seconds', flush=True)

    result = pd.DataFrame(rows)
    result.to_csv('/tmp/sentinel-tick-cache/m1_screen_results.csv', index=False)

    print('\n' + '=' * 78)
    print('IMBALANCE_5s decile spread (top decile fwd return - bottom decile), bps')
    print('=' * 78)
    pivot = result.pivot_table(index=['symbol', 'day'], columns='horizon_s', values='imbalance_spread_bps')
    print(pivot.round(2))

    print('\n' + '=' * 78)
    print('TEMPO_5s decile spread, bps')
    print('=' * 78)
    pivot2 = result.pivot_table(index=['symbol', 'day'], columns='horizon_s', values='tempo_spread_bps')
    print(pivot2.round(2))

    print('\n' + '=' * 78)
    print('SIGN STABILITY (imbalance): fraction of symbol-days with a POSITIVE spread, per horizon')
    print('=' * 78)
    for h in HORIZONS_S:
        sub = result[result.horizon_s == h]['imbalance_spread_bps'].dropna()
        print(f'  horizon={h:>3d}s  n_symbol_days={len(sub):>3d}  '
              f'positive_share={round((sub > 0).mean(), 3)}  median={round(sub.median(), 2)} bps  '
              f'mean={round(sub.mean(), 2)} bps')

    print('\nRound-trip cost assumptions (bps):', ROUND_TRIP_BPS)


if __name__ == '__main__':
    main()
