# Strategy rebuild — 2026-10-13

## Decision

- **Paper baseline:** `BOOK_AB_R5_A_PLUS_CASH` — corrected Book A receives $250 and the other $250 stays cash.
- **New paper challenger:** `S99_INDEPENDENT_DUAL_MOMENTUM_SAFE15` — own-trend-gated, long-only rotation; historical gate passed, but selection is contaminated.
- **Allocation challenger:** Book A $250 + S99 $250 — paper-only replacement for R5's cash reserve.
- **Shadow challenger:** `BOOK_AB_R4_QUIET_V2` — strict Book B v2 remains virtual only.
- **Do not deploy:** S94 Phase-C Wyckoff, S95 Phase-D Wyckoff, S96 asymmetric residual reversal.
- **Inconclusive:** S93 delta-neutral basis compression produced no episode at its frozen 132 bps cost threshold.

No result below is true OOS. All data through 2026-09-01 were inspected during research. Prospective paper time starts at `2026-10-14T00:00:00Z` and any rule change resets that clock.

## Benchmark repair

`BENCH_AB_R2` was not a valid comparison because Book A held target weights constant instead of holding quantities, and each reporting window reset both books. `BENCH_AB_R3` fixes both issues:

- Book A holds immutable quantities between weekly rebalances;
- cash is explicit;
- turnover is measured from actual drifted notionals;
- A and B run once continuously from 2025-05-01 through 2026-09-01;
- reporting windows are slices of the same NAV and risk state.

| Portfolio | Stress PnL | Return on $500 | Max DD | Interpretation |
|---|---:|---:|---:|---|
| R3 A + S84 router | $58.36 | 11.67% | 9.88% | corrected benchmark |
| R4 A + strict B v2 | $107.64 | 21.53% | 6.46% | economically better, but concentrated |
| R5 A $250 + cash $250 | **$122.15** | **24.43%** | **4.01%** | selected paper baseline |

R4 improved stress PnL by $49.28 and reduced DD, but only 31.25% of months had positive excess and the paired 28-day bootstrap lower bound was −$2.65. It therefore failed its frozen robustness gate. R5 does not claim new alpha; it removes a historically loss-making sleeve while keeping B v2 in shadow.

## New strategy results

| Strategy | Frozen mechanism | Stress result | Decision |
|---|---|---:|---|
| S94 | range → spring/UTAD → low-volume test → confirmation | −$21.74 / 48 trades | rejected |
| S95 | range → SOS/SOW → LPS/LPSY → confirmation | −$23.21 / 49 trades | rejected |
| S96 | long negative alt residual + short beta-weighted BTC | −$25.81 / 50 pairs | rejected |
| S93 | long spot + short perpetual on extreme positive basis | $0.00 / 0 episodes | inconclusive |

The Wyckoff implementations are symmetric long/short, causal and sequence-based. They are not simple support/resistance reclaims. S94 failed because early Phase-C reversals stopped too often; S95 then tested the distinct Phase-D/LPS hypothesis and also failed. Their thresholds remain frozen; none were loosened after results.

S96 implemented the professional statistical-arbitrage idea correctly as two simultaneous legs and included both-leg fees, slippage, actual funding and a hard pair stop. Mean-reversion labels did not translate into positive executable PnL after costs.

S93 used checksumed spot, perpetual and realized-funding history. The 132 bps minimum spread was intentionally set at twice stress round-trip cost. Lowering it after observing zero signals would be a new, separately frozen strategy rather than a repair of v1.

## Verification

- 39 targeted unit tests pass.
- Tests cover quantity drift and real turnover, prefix invariance, signal publication only after closed bars, Wyckoff event order, funding timestamp causality, identical base quantity on basis legs, and fees on every entry/exit leg.
- Every replay uses one continuous ledger and preserves state across report boundaries.

## Professional rationale used

- Wyckoff: trading ranges, effort versus result, spring/UTAD tests, SOS/SOW and LPS/LPSY.
- Statistical arbitrage: residual/idiosyncratic mean reversion and market-neutral hedging.
- Basis/carry: arbitrage capital links positive perpetual basis and funding to long-spot/short-perpetual convergence.

The research code and frozen protocols are in the sibling directories `bench_ab_r3`, `book_ab_r4_quiet_v2`, `book_ab_r5_a_cash`, `s93_basis_compression`, `s94_wyckoff_phase_c`, `s95_wyckoff_phase_d`, and `s96_asymmetric_residual`.

## S97–S99 slow-momentum branch

S97 tested a genuinely new long/short dual-horizon trend mechanism. It remained profitable after correcting an implementation bug that had treated an absent weekly signal as “hold” instead of the protocol's explicit flat target. Its stress result was +$306.15 on $500, but 32.06% drawdown and negative neighboring horizons failed the frozen gate.

S98 removed short-squeeze risk by requiring each asset to be above its own SMA200, ranking positive 84-day momentum across BTC and five alts, and otherwise holding cash. It produced +$420.19 under stress with broad robustness, but its 15.25% drawdown narrowly exceeded the pre-registered 15% ceiling and was rejected without moving the threshold.

S99 changed only S98's annual volatility target from 20% to 15%. On the one continuous 2023-01-02 through 2026-09-01 replay:

| Scenario | PnL on $500 | Return | Max DD | Sharpe |
|---|---:|---:|---:|---:|
| Base | $317.97 | 63.59% | 11.47% | 1.13 |
| Stress | **$307.68** | **61.54%** | **11.61%** | **1.10** |
| Severe | $295.82 | 59.16% | 11.77% | 1.07 |

Every frozen robustness check passed: 12.5% and 17.5% risk targets, 63d and 126d momentum neighbors, Wednesday and Friday rebalances, and all six leave-one-symbol-out runs remained profitable. The 28-day block bootstrap's 10th-percentile terminal PnL was +$73.32. This is historical selection evidence only; 2025 through August 2026 contributed just +$10.83 under stress, so S99 is not promoted over R5 without prospective data.

On the common 2025-05-01 through 2026-09-01 diagnostic, allocating R5's $250 cash reserve to S99 increased stress PnL from the official $122.15 to $139.10 and the average from $7.62 to $8.68 per month. Drawdown increased from 4.01% to 5.11%; daily PnL correlation was 0.026. Because this allocation was examined after S99 was selected, it starts a new paper-forward clock and is not a live recommendation.
