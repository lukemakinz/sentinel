# L2B-REV — pre-registered hypothesis (frozen before any new data is seen)

Registered: 2026-09-17, immediately before the L2A ALPHA→EXECUTION AUDIT,
on the basis of the L2-EDGE result computed on the 6 discovery days
(2025-08-01, 09-01, 10-01, 11-01, 12-01, 2026-01-01).

## Origin

L2B (absorption reversal, "fade the consuming side") showed, on the
6-day L2-EDGE sample, h=5s, latency=250ms:

- exec_mean = -0.421 bps (opposite sign to the hypothesized direction)
- 95% block-bootstrap CI (by day): [-0.480, -0.375] — excludes zero
- Stable sign under leave-one-day-out (all 6 folds: -0.34 to -0.55)
- Stable sign under leave-one-symbol-out (all 3 folds: -0.20 to -0.55)
- Magnitude larger than L2A's +0.170 bps

This is data-driven — the direction was NOT predicted in advance — so it
cannot be used as evidence for a strategy. It is registered here only as
the exact definition of a new hypothesis, to be tested later on unseen
data.

## Hypothesis definition (frozen, do not modify after seeing new-day results)

**L2B-REV = continuation, not fade.**

Same trigger as L2B (`l2_signals.py`, mechanism `'L2B'`: one side's top-of-book
depth collapses sharply — `z(depth1_ask.diff()) <= -2.0` or
`z(depth1_bid.diff()) <= -2.0` — while `|mid_ret3| < 1.0 bps`), but the
trade direction is **reversed**:

- Old L2B: `z_d1a extreme → SHORT` (fade the ask-side consumption),
  `z_d1b extreme → LONG` (fade the bid-side consumption)
- L2B-REV: `z_d1a extreme → LONG`, `z_d1b extreme → SHORT`
  (i.e., trade in the direction the consumed side implies — the side
  whose depth got eaten is where price is about to go, not away from it)

No other change: same `ZSCORE_WINDOW=120`, same `ZSCORE_EXTREME=2.0`,
same `|mid_ret3|<1.0bps` filter, same dedup-on-transition logic.

## Test conditions (binding)

1. **New, previously unseen calendar days only.** Not the 6 discovery
   days above. A different month (or several) must be pulled fresh from
   Tardis.dev.
2. **No threshold changes.** `ZSCORE_EXTREME`, `ZSCORE_WINDOW`, the
   `mid_ret3` filter, and the symbol universe (BTC+ETH+SOL, all three,
   no post-hoc dropping) are frozen exactly as above.
3. **Report format identical to L2A's L2-EDGE + ALPHA→EXECUTION AUDIT**:
   gross/exec/net bps by horizon, block-bootstrap CI (by day, with the
   exact day count disclosed), leave-one-day-out, leave-one-symbol-out,
   concentration in top 1%/5% events, then (if the info test clears) the
   same A/B/C/D alpha waterfall.
4. Not to be run until the L2A ALPHA→EXECUTION AUDIT is complete and
   reported.

## Decision rule (same CASE framework as L2A)

- CASE A (gross expectancy from real fill ≤ 0) → close L2B-REV.
- CASE B (gross expectancy > 0 but sub-cost) → close at current execution economics.
- CASE C (gross expectancy clearly positive, MICRO-SIM loss traceable to a
  fixable execution element) → separate execution study, not before.
