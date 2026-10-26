"""Single canonical source for the L2-A/B/C signal definitions and the
shared constants (universe, sample days, z-score window/threshold).
Previously duplicated with small drifts across run_l2_hist_backtest.py,
run_l2_microsim.py and run_l2_edge_audit.py (e.g. one still called the
depth-change feature 'ofi', another had already renamed it to the more
honest 'depth_imbalance_delta') -- consolidated here so every L2 script
imports the exact same frozen definitions instead of a hand-copied
approximation of them.

generate_signals() returns ONLY the bare trigger -- decision_ts, side,
symbol, mechanism -- deliberately no stop/target/vol_unit, since those
are execution-specific concerns each caller (MICRO-SIM, L2-EDGE, or any
future execution model) should own separately.

Four frozen mechanisms (z >= ZSCORE_EXTREME, not swept):
  L2-A pressure continuation: imbalance5 AND depth_imbalance_delta
       z-extreme, same sign -> trade WITH the pressure.
  L2-B absorption reversal: one side's top depth collapses sharply
       while price barely moved -> fade AGAINST the consuming side.
  L2-C liquidity vacuum: one side's 5-level depth collapses sharply
       -> trade TOWARD the thin side.
  L2B-REV: same trigger as L2-B, direction reversed (continuation, not
       fade) -- pre-registered 2026-09-17 after L2-B showed a stable,
       leave-one-out-robust NEGATIVE effect on the discovery sample; see
       docs/research/l2b_rev_hypothesis.md. Not to be evaluated on the
       6 discovery DAYS below -- OOS only.

DAYS below is the DISCOVERY set only (L2-EDGE + L2A audit). Stage-1 OOS
and holdout dates for L2A-5S/L2B-REV-5S live in run_l2_oos_stage1.py,
deliberately not added here, so the discovery/OOS split can never be
silently blurred by a future import.
"""
import numpy as np
import pandas as pd

SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
DAYS = ['2025-08-01', '2025-09-01', '2025-10-01', '2025-11-01', '2025-12-01', '2026-01-01']
ZSCORE_WINDOW = 120  # bars (60s at 500ms)
ZSCORE_EXTREME = 2.0


def zscore(series: pd.Series, window: int = ZSCORE_WINDOW) -> pd.Series:
    mean = series.shift(1).rolling(window, min_periods=window).mean()
    std = series.shift(1).rolling(window, min_periods=window).std()
    return (series - mean) / std.where(std > 0)


def generate_signals(bars: pd.DataFrame, symbol: str, mechanism: str) -> list[dict]:
    """`bars` must have columns: mid, imbalance5, depth_imbalance_delta,
    depth1_bid, depth1_ask, depth5_bid, depth5_ask (the standard L2
    feature-bar schema built by download_l2_hist.build_feature_bars /
    download_l2_edge.build_tob_and_bars)."""
    n = len(bars)
    z_imb5 = zscore(bars.imbalance5).to_numpy()
    z_did = zscore(bars.depth_imbalance_delta).to_numpy()
    mid_ret3 = (bars.mid.pct_change(3) * 10_000).to_numpy()
    z_d1a = zscore(bars.depth1_ask.diff()).to_numpy()
    z_d1b = zscore(bars.depth1_bid.diff()).to_numpy()
    z_d5a = zscore(bars.depth5_ask.diff()).to_numpy()
    z_d5b = zscore(bars.depth5_bid.diff()).to_numpy()
    timestamps = bars.index

    records = []
    prev_fired = False
    for i in range(n):
        fired, side = False, 0
        if mechanism == 'L2A':
            if np.isfinite(z_imb5[i]) and np.isfinite(z_did[i]):
                if z_imb5[i] >= ZSCORE_EXTREME and z_did[i] >= ZSCORE_EXTREME:
                    fired, side = True, 1
                elif z_imb5[i] <= -ZSCORE_EXTREME and z_did[i] <= -ZSCORE_EXTREME:
                    fired, side = True, -1
        elif mechanism == 'L2B':
            if np.isfinite(z_d1a[i]) and np.isfinite(mid_ret3[i]) and abs(mid_ret3[i]) < 1.0:
                if z_d1a[i] <= -ZSCORE_EXTREME:
                    fired, side = True, -1
                elif z_d1b[i] <= -ZSCORE_EXTREME:
                    fired, side = True, 1
        elif mechanism == 'L2B-REV':
            # Pre-registered 2026-09-17 (docs/research/l2b_rev_hypothesis.md),
            # BEFORE any Stage-1 OOS data was touched. Same trigger as L2B,
            # direction flipped: L2B on 6 discovery days gave a stable,
            # leave-one-out-robust -0.421bps in the FADE direction, so
            # CONTINUATION is the frozen hypothesis to test on new days.
            if np.isfinite(z_d1a[i]) and np.isfinite(mid_ret3[i]) and abs(mid_ret3[i]) < 1.0:
                if z_d1a[i] <= -ZSCORE_EXTREME:
                    fired, side = True, 1
                elif z_d1b[i] <= -ZSCORE_EXTREME:
                    fired, side = True, -1
        elif mechanism == 'L2C':
            if np.isfinite(z_d5a[i]) and z_d5a[i] <= -ZSCORE_EXTREME:
                fired, side = True, 1
            elif np.isfinite(z_d5b[i]) and z_d5b[i] <= -ZSCORE_EXTREME:
                fired, side = True, -1
        else:
            raise ValueError(f'Unknown mechanism {mechanism!r}')

        if not fired or prev_fired:
            prev_fired = fired
            continue
        prev_fired = True
        records.append({'decision_ts': timestamps[i], 'side': side, 'symbol': symbol, 'mechanism': mechanism})
    return records
