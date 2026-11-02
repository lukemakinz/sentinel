# S118 — timeframe x parameter robustness, random control, confluence

Protocol `protocol.json` (frozen before results). 10 symbols, 2024-01..2026-10,
H3B logic on 15m/1h/4h x 27 entry variants x 2 exits = 162 configs, stress costs,
174,371 simulated trades in total. Detector parity with the H3B replay: 100%
(BTC 70/70, ETH 77/77).

## Decision: **REJECTED** (steps 1-2)

| fold | chosen (on train) | train mean R | test year | test mean R | plateau | vs random |
|---|---|---|---|---|---|---|
| 1 | 4h, w3, e1.0, d2, E2 | +0.49 (82) | 2025 | **+0.14** (77) | 0.77 | +0.13 |
| 2 | 4h, w2, e0.5, d2, E2 | +0.41 (174) | 2026 | **−0.34** (64) | 0.67 | −0.60 |

OOS combined: −0.08 R/trade, 95% CI −0.46..+0.34; vs random −0.20 (CI −0.59..+0.22).

## Answers to the three questions

**Wrong timeframe?** Partly. Mean net R by TF and exit (all years):

| TF | E1 (2R, 72 bars) | E2 (no target, 168 bars) |
|---|---|---|
| 15m | −0.16 | −0.12 |
| 1h | −0.07 | +0.07 |
| 4h | −0.10 | +0.06 |

15m loses everywhere. 1h/4h are positive only with the let-winners-run exit.

**Wrong parameters?** Not in the overfitting sense: chosen configs sat on broad
positive plateaus (67-77% of neighbours positive in training). The failure is
**instability over time**: 4h E2 was +0.21 (2024), +0.14 (2025), **−0.21 (2026)**;
1h E2 was +0.01, +0.01, **+0.24**. The best region moves between years.

**Missing confluence?** Measured on 2024-2025 (470 trades, FDR 10%):

* **No information:** trend strength on the higher TF, daily trend vs SMA200, ADX,
  RSI level at the second extreme, **divergence size**, session, BTC alignment, funding.
* **Information in development:** risk % (rho 0.58), ATR percentile (0.27), pattern
  height (0.20), breakout volume (0.13) — all volatility/size features.
* **Out of sample (2026):** none of them significantly improved results; ATR
  percentile and risk % filters made 2026 worse; volume +0.47 vs +0.40 unfiltered
  (CI −0.17..+1.22).

## Robust lessons across H3B, S117 and S118

1. Exit matters more than the pattern: letting winners run beats a fixed 2R on every
   timeframe >= 1h.
2. The pattern itself (double bottom/top + divergence) adds no information.
3. Edges in this family are regime/time dependent; parameter tuning cannot fix that.
