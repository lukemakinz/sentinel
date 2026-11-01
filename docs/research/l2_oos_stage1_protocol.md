# L2 OOS Stage 1 — frozen protocol for L2A-5S and L2B-REV-5S

Registered: 2026-09-17, before touching any Stage 1 data. Supersedes/extends
`l2b_rev_hypothesis.md` (that file's signal definition is unchanged and
still authoritative; this file adds L2A-5S, the fixed-5s execution model,
and the audit-amended date split below).

## Audit amendment (disclosed, made before touching new data)

The original plan called for 12 Stage-1 days (1st and 15th of each month,
2026-02 through 2026-07) + 2 holdout days (2026-08-01, 2026-08-15).
Checked directly against Tardis.dev before downloading anything:

```
GET .../2026/03/15/BTC-USDT-SWAP.csv.gz -> 401
{"message": "For unauthorized requests, only historical CSV market
datasets for the first day of each month are available ..."}
```

The free sample is 1st-of-month only — every 15th-of-month date in the
original plan is paywalled. User decision: reduce to the 1st-of-month
dates only, split 6 Stage-1 / 2 holdout instead of 12/2.

**Frozen dates (final, do not add/drop/reorder after this point):**

- Stage 1 (6 days × BTC/ETH/SOL = 18 symbol-days): `2026-02-01`,
  `2026-03-01`, `2026-04-01`, `2026-05-01`, `2026-06-01`, `2026-07-01`
- Final holdout (untouched until Stage 1 gate passes): `2026-08-01`,
  `2026-09-01`
- None of these overlap the 6 discovery days used for L2-EDGE /
  L2A-audit (`2025-08-01, 09-01, 10-01, 11-01, 12-01, 2026-01-01`).

## Hypothesis 1 (PRIMARY): L2B-REV-5S

Signal: exactly `l2_signals.py` mechanism `'L2B-REV'` (added as a new
frozen mechanism, reusing the L2B trigger condition with the direction
flipped — see `l2b_rev_hypothesis.md` for the exact definition and why).

## Hypothesis 2 (SECONDARY): L2A-5S

Signal: exactly `l2_signals.py` mechanism `'L2A'`, unchanged. Universe
stays BTC+ETH+SOL primary; SOL is not dropped (dropping it now would be
post-hoc — the L2A audit showed SOL was the only symbol with positive
gross expectancy on the actual exit engine, so keeping it is if anything
conservative against this hypothesis, not for it).

## Execution model (both hypotheses, identical)

- Entry: real executable bid (short) / ask (long) at decision_ts + 250ms
  (PRIMARY). 500ms and 1000ms latency reported as sensitivity only —
  never used to pick a result.
- Exit: real executable ask (short) / bid (long) at decision_ts + 5s
  exactly. No stop-loss, no target, no trailing, no time filter. 5s is
  L2-EDGE's own pre-declared primary horizon, not chosen after seeing
  the audit's exit curve.
- One open position at a time per symbol (same discipline as MICRO-SIM);
  a signal while a position is open is skipped, not queued.
- Position sizing: identical convention to MICRO-SIM/prior work —
  `risk_usd = min(cash * 0.0020, $0.50)`, `qty = risk_usd / vol_unit`
  (vol_unit = 60s/120-bar rolling std of cumulative log returns, same as
  before). There is no stop-loss here, so vol_unit is used only as the
  risk-normalization unit for sizing and R-multiples, not as an actual
  exit trigger.
- Costs, explicitly separated (to avoid double-counting spread):
  - **Spread**: already inside the entry/exit price, since both are the
    real crossed bid/ask from the native-resolution TOB series. Not
    modeled separately.
  - **Fees**: BASE = 5bps taker each side (10bps round trip). STRESS =
    8bps taker each side (16bps round trip).
  - **Extra modeled slippage**: BASE = 0 (none — the real bid/ask
    already is the fill price). STRESS = +3bps each side, a deliberately
    conservative buffer for walking size beyond the top-of-book quote,
    which this model does not otherwise account for.
- Capital: each symbol run independently with its own $250 (same
  convention as MICRO-SIM). Reported total $ is a **sum of independently
  restarted $250 books**, not one shared account — disclosed again here
  explicitly per standing instruction not to imply otherwise.

## Mandatory report

signals, fills, fill rate, trades/day, gross mean bps/trade, net mean
bps/trade, gross PF, net PF, gross expectancy R, net expectancy R, win
rate, avg win/avg loss, total net PnL on $250 (per symbol, summed),
net $/day, max drawdown, per symbol, per calendar day, base vs stress,
block-bootstrap CI by day (6 independent blocks — width disclosed
honestly, not oversold).

## Stage 1 gate (binding, no re-optimization after seeing results)

Advances only if ALL of:
1. net expectancy > 0
2. net PF > 1
3. bootstrap CI for mean net effect is not clearly compatible with a
   large negative edge
4. sign is reasonably stable across days
5. result is not dominated by one symbol or one day

A positive result below the eventual +0.15R/trade business target still
advances — the gate question is "does monetizable edge exist," not yet
"does it hit the $5/day target."

## Final confirmation (only if a hypothesis clears the Stage 1 gate)

Code and parameters get a SHA/hash freeze *before* touching
`2026-08-01` / `2026-09-01`. No further changes after that point. If
Stage 1 fails, the holdout is not touched for that hypothesis at all.
