# S35 — read-only signal-funnel audit

This audit decomposes the already-frozen S35 rules. It does not change any
threshold, market, replay result or promotion decision. It reuses the same
checksum-pinned public Binance inputs, causal funding timestamps and
`PFEConfig()` used by `results.json`.

## Result

S35 is **far too selective for the stated historical trade-count gates**.
Across 24,172 funding settlements in the three replay windows, only two
deterministic candidates survive (`0.0083%` of settlements), both DOGE shorts
in the validation window. Only one is executable at $250 because the other is
below the frozen $20 minimum notional.

The principal bottlenecks are:

1. The combined extreme-funding threshold
   `abs(funding) >= max(0.0005, trailing Q95)` leaves 248 of 23,413 events with
   complete causal histories (`1.06%`).
2. Requiring an extreme same-direction 60-minute extension leaves 41 of those
   248 (`16.53%`).
3. After the one-bar reversal gate, premium compression leaves only 2 of 23
   (`8.70%`). It eliminates every surviving reversal in development and
   retrospective evaluation.

Exact event-bar availability, ATR, liquidity history and subsequent 180-minute
price coverage eliminate **none** of the events that reach them. Consequently,
the near-zero trade count is a rule-selectivity result, not a missing-data
artifact.

## Aggregate cumulative funnel

Each row is cumulative. `Pass previous` measures survival from the immediately
preceding row, not an independent condition.

| Gate | Development | Validation | Retrospective evaluation | All windows | Pass previous, all |
|---|---:|---:|---:|---:|---:|
| Funding settlements whose entry time is inside window | 6,802 | 5,490 | 11,880 | 24,172 | — |
| At least 180 earlier realized funding observations | 6,627 | 5,485 | 11,880 | 23,992 | 99.26% |
| Current and prior 180 exact 60m event returns complete | 6,049 | 5,484 | 11,880 | 23,413 | 97.59% |
| Extreme funding: max(5 bps, trailing Q95) | 45 | 165 | 38 | 248 | 1.06% |
| Extreme 60m move, same sign as funding | 6 | 29 | 6 | 41 | 16.53% |
| Exact pre/post perpetual, mark and index bars | 6 | 29 | 6 | 41 | 100.00% |
| Signed pre-premium at least 3 bps | 6 | 28 | 5 | 39 | 95.12% |
| First post-settlement bar reverses direction | 3 | 19 | 1 | 23 | 58.97% |
| Post-premium no more than 75% of pre-premium | 0 | 2 | 0 | 2 | 8.70% |
| ATR and prior 12-bar quote liquidity complete | 0 | 2 | 0 | 2 | 100.00% |
| Final deterministic candidate | 0 | 2 | 0 | 2 | 100.00% |
| Entry plus complete 180m holding data | 0 | 2 | 0 | 2 | 100.00% |
| Executable with frozen sizing/minimum notional at $250 | 0 | 1 | 0 | 1 | 50.00% |

Window-specific survival confirms instability rather than a uniformly active
effect:

- Development: 6,049 complete histories -> 45 funding extremes -> 6 aligned
  moves -> 3 reversals -> **0 compressions**.
- Validation: 5,484 -> 165 -> 29 -> 19 -> **2 compressions**.
- Retrospective evaluation: 11,880 -> 38 -> 6 -> 1 -> **0 compressions**.

## Per-symbol cumulative counts

Abbreviations: `Raw` settlements; `F180` funding history; `R180` return
history; `F-ext` extreme funding; `Move` aligned extreme move; `Bars` exact
event bars; `Prem` signed premium; `Rev` reversal; `Comp` compression;
`Data` ATR/liquidity; `Cand` deterministic candidate; `Hold` complete holding
path; `Exec` executable at $250.

| Window | Symbol | Raw | F180 | R180 | F-ext | Move | Bars | Prem | Rev | Comp | Data | Cand | Hold | Exec |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Development | SUIUSDT | 175 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Development | DOGEUSDT | 1,638 | 1,638 | 1,638 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Development | XRPUSDT | 1,638 | 1,638 | 1,349 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Development | SOLUSDT | 1,713 | 1,713 | 1,424 | 25 | 5 | 5 | 5 | 2 | 0 | 0 | 0 | 0 | 0 |
| Development | ETHUSDT | 1,638 | 1,638 | 1,638 | 10 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| Validation | SUIUSDT | 1,098 | 1,093 | 1,092 | 43 | 3 | 3 | 3 | 1 | 0 | 0 | 0 | 0 | 0 |
| Validation | DOGEUSDT | 1,098 | 1,098 | 1,098 | 31 | 7 | 7 | 7 | 6 | 2 | 2 | 2 | 2 | 1 |
| Validation | XRPUSDT | 1,098 | 1,098 | 1,098 | 26 | 5 | 5 | 5 | 4 | 0 | 0 | 0 | 0 | 0 |
| Validation | SOLUSDT | 1,098 | 1,098 | 1,098 | 40 | 9 | 9 | 8 | 5 | 0 | 0 | 0 | 0 | 0 |
| Validation | ETHUSDT | 1,098 | 1,098 | 1,098 | 25 | 5 | 5 | 5 | 3 | 0 | 0 | 0 | 0 | 0 |
| Retrospective | SUIUSDT | 2,376 | 2,376 | 2,376 | 12 | 3 | 3 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| Retrospective | DOGEUSDT | 2,376 | 2,376 | 2,376 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Retrospective | XRPUSDT | 2,376 | 2,376 | 2,376 | 4 | 2 | 2 | 2 | 1 | 0 | 0 | 0 | 0 | 0 |
| Retrospective | SOLUSDT | 2,376 | 2,376 | 2,376 | 15 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| Retrospective | ETHUSDT | 2,376 | 2,376 | 2,376 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

SUI appears for only 175 settlements at the end of the development window and
therefore cannot reach the required 180-event history there. The 579 aggregate
return-history failures are concentrated in the early XRP/SOL archive region;
they do not explain the later validation/evaluation collapse.

## The two final candidates

| Funding T | Symbol/side | Funding | 60m return | Pre premium | Post premium | Liquidity cap | Frozen $250 outcome |
|---|---|---:|---:|---:|---:|---:|---|
| 2024-02-28 16:00 UTC | DOGEUSDT short | 0.060162% | 0.723691% | 0.086375% | 0.060270% | $2,208.35 | Executable: 322 DOGE, $32.17 notional; recorded -$0.4997 stress |
| 2024-03-02 08:05 UTC | DOGEUSDT short | 0.087727% | 3.473046% | 0.138058% | 0.092846% | $5,360.53 | Blocked: after the prior loss, sequential sizing gives 131 DOGE and $19.21 notional, below the frozen $20 minimum |

The second funding timestamp is the causal 5-minute ceiling of the raw public
`calc_time`, as required by the frozen loader; it is never rounded backward.
At a standalone $250 equity this event would size to 132 DOGE and $19.35,
which is still below the minimum. The sequential replay correctly uses the
slightly lower equity remaining after the first trade.

## Interpretation boundary

This funnel identifies where S35 loses sample size. It does **not** establish
that relaxing any particular gate would create positive expectancy. In
particular, changing the 5 bps funding floor or the 75% compression ratio after
seeing this audit would be a new hypothesis requiring a separately frozen
protocol and untouched evaluation period. The current S35 remains rejected.
