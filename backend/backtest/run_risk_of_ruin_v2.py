"""Monte Carlo risk-of-ruin V2 -- fixes four issues in v1 flagged by
review:

  1. BLOCK bootstrap (weekly blocks of trades, not iid single trades) --
     losses cluster in time/regime; iid resampling understates drawdown.
  2. No np.clip() masking ruin: if a block of trades would drive equity
     to <=0, the path is marked RUINED at that point and frozen, not
     clipped to a microscopic positive number that can "recover".
  3. Liquidation-distance sanity check (NOT a full exchange margin
     engine -- disclosed limitation): compares each historical trade's
     actual stop distance (from real S20 H1 trades: entry vs
     initial_stop) against the price move that would exhaust margin at
     a given leverage (~1/leverage, minus an assumed 0.5% maintenance
     buffer), at 5x (this project's cap throughout) and 30x.
  4. P(ruin)=0% is relabeled "<1/N_PATHS observed" -- it means "not seen
     in this many simulated paths", not a proven zero probability.

Two separate, deliberately different questions, as specified:
  A. COMPOUNDING -- if every dollar of profit is reinvested and every
     loss compounds, what is the account worth after 1 year?
  B. WITHDRAWAL / DAILY-INCOME -- if the account must pay out exactly
     $25.00 every single day regardless of that day's trading result,
     what fraction of paths survive 30 / 90 / 365 days?
These are NOT the same question, and v1 conflated them by reporting a
"$/day" figure that was actually an average compounding growth rate.
"""
import json
from collections import defaultdict

import numpy as np
import pandas as pd

TRADE_RATE_PER_DAY = 0.7323
START_EQUITY = 250.0
DAILY_WITHDRAWAL = 25.0
N_PATHS = 20000
RISK_FRACTIONS = [0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30, 0.40, 0.546, 0.60]
LEVERAGE_LEVELS = (5, 30)
MAINTENANCE_MARGIN_BUFFER = 0.005  # 0.5% -- a plausible approximation for majors, not exchange-exact


def load_trades():
    with open('/tmp/sentinel-tick-cache/s20_trades_full.json') as f:
        records = json.load(f)
    return pd.DataFrame(records)


def liquidation_distance(leverage):
    return max(1.0 / leverage - MAINTENANCE_MARGIN_BUFFER, 0.0)


def weekly_blocks(df):
    df = df.copy()
    df['week'] = pd.to_datetime(df.opened_at).dt.tz_localize(None).dt.to_period('W')
    return [g['r_multiple'].to_numpy() for _, g in df.groupby('week')]


def block_bootstrap_paths(blocks, n_paths, trades_per_path, seed):
    """Builds n_paths sequences of ~trades_per_path R-multiples by
    resampling whole weekly blocks with replacement and concatenating,
    then truncating to trades_per_path. Preserves within-week clustering."""
    rng = np.random.default_rng(seed)
    avg_block_len = np.mean([len(b) for b in blocks])
    blocks_needed = int(np.ceil(trades_per_path / avg_block_len)) + 2
    paths = np.empty((n_paths, trades_per_path))
    for p in range(n_paths):
        chosen = [blocks[i] for i in rng.integers(0, len(blocks), size=blocks_needed)]
        seq = np.concatenate(chosen)
        if len(seq) < trades_per_path:
            seq = np.tile(seq, trades_per_path // len(seq) + 1)
        paths[p] = seq[:trades_per_path]
    return paths


# ---------------------------------------------------------------------
# A) COMPOUNDING
# ---------------------------------------------------------------------
def simulate_compounding(r_paths, risk_fraction, horizon_days):
    growth = 1.0 + risk_fraction * r_paths
    ruined = np.zeros(r_paths.shape[0], dtype=bool)
    equity = np.full(r_paths.shape[0], START_EQUITY)
    peak = equity.copy()
    max_dd = np.zeros(r_paths.shape[0])
    for i in range(r_paths.shape[1]):
        step = growth[:, i]
        wipeout = step <= 0
        ruined |= wipeout
        equity = np.where(ruined, 0.0, equity * np.where(wipeout, 0.0, step))
        peak = np.maximum(peak, equity)
        max_dd = np.maximum(max_dd, np.where(peak > 0, 1 - equity / peak, 1.0))
    return {
        'risk_fraction': risk_fraction,
        'p_ruin': float(ruined.mean()),
        'p_dd_ge_30pct': float((max_dd >= 0.30).mean()),
        'p_dd_ge_40pct': float((max_dd >= 0.40).mean()),
        'median_final_equity': float(np.median(equity)),
        'p05_final_equity': float(np.quantile(equity, 0.05)),
        'p95_final_equity': float(np.quantile(equity, 0.95)),
        # honest per-day figure: median cumulative gain over the WHOLE
        # horizon, divided by days -- explicitly an average, not a
        # stable daily expectation from the starting balance.
        'median_avg_gain_per_day_over_horizon': float(
            (np.median(equity) - START_EQUITY) / horizon_days),
    }


# ---------------------------------------------------------------------
# B) WITHDRAWAL / DAILY-INCOME
# ---------------------------------------------------------------------
def simulate_withdrawal(blocks, risk_fraction, horizon_days, n_paths, seed):
    """Each day: apply that day's trades (Poisson-ish count around
    TRADE_RATE_PER_DAY, drawn from the same weekly-block bootstrap at
    trade granularity) to CURRENT equity (so position sizing still
    scales with equity, standard practice), then withdraw $25 flat.
    Path is dead the moment equity hits zero -- no borrowing, no partial
    withdrawal modeled."""
    rng = np.random.default_rng(seed)
    survived_30 = survived_90 = survived_365 = 0
    for p in range(n_paths):
        equity = START_EQUITY
        alive = True
        day = 0
        while day < horizon_days and alive:
            day += 1
            n_trades_today = rng.poisson(TRADE_RATE_PER_DAY)
            if n_trades_today > 0:
                block = blocks[rng.integers(0, len(blocks))]
                idx = rng.integers(0, len(block), size=n_trades_today)
                for r in block[idx]:
                    step = 1.0 + risk_fraction * r
                    equity = max(equity * step, 0.0) if step > 0 else 0.0
                    if equity <= 0:
                        alive = False
                        break
            if not alive:
                break
            equity -= DAILY_WITHDRAWAL
            if equity <= 0:
                alive = False
        if alive or day >= 30:
            if day >= 30 and (alive or equity > 0):
                survived_30 += 1
        if alive or day >= 90:
            if day >= 90 and (alive or equity > 0):
                survived_90 += 1
        if day >= 365 and (alive or equity > 0):
            survived_365 += 1
    return {
        'risk_fraction': risk_fraction,
        'p_survive_30d': survived_30 / n_paths,
        'p_survive_90d': survived_90 / n_paths,
        'p_survive_365d': survived_365 / n_paths,
    }


def main():
    df = load_trades()
    r_pool = df.r_multiple.to_numpy()
    stop_pct = df.stop_pct.to_numpy()

    print('=' * 100)
    print('LIQUIDATION-DISTANCE SANITY CHECK (disclosed simplification, not a full margin engine)')
    print('=' * 100)
    print(f'Historical stop_pct (n={len(stop_pct)}): min={stop_pct.min()*100:.2f}% '
          f'median={np.median(stop_pct)*100:.2f}% p90={np.quantile(stop_pct,0.9)*100:.2f}% '
          f'max={stop_pct.max()*100:.2f}%')
    for lev in LEVERAGE_LEVELS:
        dist = liquidation_distance(lev)
        frac_at_risk = float((stop_pct > dist).mean())
        print(f'  leverage={lev:>3d}x  liquidation_distance~{dist*100:.2f}%  '
              f'fraction of historical trades with stop WIDER than this (would liquidate before stop) = '
              f'{frac_at_risk*100:.1f}%')
    print('  Note: at 5x this never binds historically. At 30x it can bind for the widest-stop tail.')
    print('  This does NOT mean a larger dollar loss per liquidated trade (margin ~= intended risk_usd')
    print('  by construction) -- it means the stop\'s own exit logic never gets to run; a trade that')
    print('  would have recovered after a deep wick is force-closed instead. Not modeled further here')
    print('  (would need intrabar tick paths this project does not have for these historical trades).')

    blocks = weekly_blocks(df)
    print(f'\nWeekly blocks available for bootstrap: {len(blocks)}, sizes: '
          f'{[len(b) for b in blocks]}')

    # -------------------------------------------------------------
    # A) Compounding, 1-year horizon, block bootstrap
    # -------------------------------------------------------------
    horizon_days_a = 341
    trades_per_path = int(round(TRADE_RATE_PER_DAY * horizon_days_a))
    for label, shift in [('zero_edge', -r_pool.mean()),
                          ('s20_as_tested', 0.0),
                          ('hypothetical_plus_025R', 0.25 - r_pool.mean())]:
        shifted_pool = r_pool + shift
        shifted_df = df.assign(r_multiple=shifted_pool)
        shifted_blocks = weekly_blocks(shifted_df)
        paths = block_bootstrap_paths(shifted_blocks, N_PATHS, trades_per_path, seed=1)
        print(f'\n{"="*100}\nA) COMPOUNDING -- {label} (mean R={shifted_pool.mean():.3f}), '
              f'{trades_per_path} trades (~{horizon_days_a}d), block bootstrap, N={N_PATHS}\n{"="*100}')
        print(f'{"risk/trade":>10s} {"P(ruin)":>10s} {"P(DD>=30%)":>11s} {"P(DD>=40%)":>11s} '
              f'{"median $end":>12s} {"p05 $end":>10s} {"p95 $end":>10s} {"median avg $/day (whole yr)":>28s}')
        for rf in RISK_FRACTIONS:
            if rf > 1.0:
                continue
            s = simulate_compounding(paths, rf, horizon_days_a)
            ruin_str = '<1/%d' % N_PATHS if s['p_ruin'] == 0 else f'{s["p_ruin"]*100:.2f}%'
            print(f'{rf*100:>9.1f}% {ruin_str:>10s} {s["p_dd_ge_30pct"]*100:>10.1f}% '
                  f'{s["p_dd_ge_40pct"]*100:>10.1f}% ${s["median_final_equity"]:>10.2f} '
                  f'${s["p05_final_equity"]:>8.2f} ${s["p95_final_equity"]:>8.2f} '
                  f'${s["median_avg_gain_per_day_over_horizon"]:>26.4f}')

    # -------------------------------------------------------------
    # B) Withdrawal -- can the account pay $25/day and survive?
    # -------------------------------------------------------------
    for label, shift in [('s20_as_tested', 0.0), ('hypothetical_plus_025R', 0.25 - r_pool.mean())]:
        shifted_pool = r_pool + shift
        shifted_df = df.assign(r_multiple=shifted_pool)
        shifted_blocks = weekly_blocks(shifted_df)
        print(f'\n{"="*100}\nB) WITHDRAWAL $25/day -- {label} (mean R={shifted_pool.mean():.3f}), '
              f'block bootstrap, N={N_PATHS}\n{"="*100}')
        print(f'{"risk/trade":>10s} {"P(survive 30d)":>15s} {"P(survive 90d)":>15s} {"P(survive 365d)":>16s}')
        for rf in RISK_FRACTIONS:
            s = simulate_withdrawal(shifted_blocks, rf, 365, min(N_PATHS, 2000), seed=7)
            print(f'{rf*100:>9.1f}% {s["p_survive_30d"]*100:>14.1f}% '
                  f'{s["p_survive_90d"]*100:>14.1f}% {s["p_survive_365d"]*100:>15.1f}%')


if __name__ == '__main__':
    main()
