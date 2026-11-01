# Auction management v1.2 — SOL retrospective diagnostic

**Period:** 2024-01-01 → 2026-10-01  
**Symbol:** SOLUSDT  
**Candidates:** 13,180  
**Filled canonical plans:** 3,988  
**Status:** research only; selection-contaminated retrospective diagnostic.

This run held candidate generation, entry, initial structural stop, candle
ordering and costs constant. Only the frozen exit-management policy changed.
P1/P2 were implemented and tested before this run. The test does not authorize
paper or live execution and is not out-of-sample evidence.

| Policy | Trades | TP1 hit | Win rate | Mean net R/trade | Net R/candidate | Total R | PF | $/day* |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 static 1.5R | 3,988 | — | 30.62% | -0.9077 | -0.2746 | -3,619.75 | 0.278 | -4.507 |
| P1 50% @ 0.75R, protected remainder | 3,988 | 43.15% | 34.00% | -0.9283 | -0.2809 | -3,702.26 | 0.116 | -4.609 |
| P2 risk-cut + two partials + runner | 3,988 | 40.50% | 30.07% | -0.9522 | -0.2881 | -3,797.35 | 0.099 | -4.728 |

\* `$1.25/R`, shown only to preserve the project reporting convention. The
candidate stream permits overlapping positions and is not a deployable
portfolio PnL forecast.

Paired day-block bootstrap uplift per candidate:

- P1 − P0: **−0.0063R**, 95% CI `[-0.0140, +0.0016]`, `P(uplift≤0)=0.9388`;
- P2 − P0: **−0.0135R**, 95% CI `[-0.0217, −0.0050]`, `P(uplift≤0)=0.9994`.

## Verdict

`REJECTED_FOR_M0` for both P1 and P2. Active management increased the frequency
of partial profit events but did not create positive expectancy. P2
statistically worsened the already losing baseline; P1 had no detectable
positive effect.

P1/P2 remain valuable infrastructure and may be tested unchanged with the new,
structurally different `SENTINEL_INTRADAY_V2` entries. They must not be tuned
again on M0. The next source of edge must be candidate formation, naturally
wider structural risk and entry economics, not cosmetic exit optimization.
