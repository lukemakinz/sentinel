# OB/SR research program — corrected benchmark and frozen candidates

Date: 2026-10-12. This is retrospective research, not a live-trading approval.

## Outcome

No tested OB/SR candidate is better than the corrected Book A+B benchmark.
S90, S91 and S92 were rejected at the development gate, so their validation
and retrospective-evaluation windows remained locked.

The practical result is therefore:

1. retain corrected Book A + exact S84 as the active historical benchmark;
2. keep FCM_SAFE25 only as a defensive paper-forward candidate;
3. do not add the tested OB/SR sleeve and do not deploy it live;
4. stop tuning the first-contact/reclaim family on these historical windows.

## Why the old A+B headline changed

The old A+B reports were generated before the Book A simulator fix that keeps
unused allocation in cash. The earlier implementation re-normalized surviving
weights to 100% gross, cancelling volatility targeting and the risk overlay.
`BENCH_AB_R2` rebuilds the benchmark with the corrected simulator and exact
S84 router, without a manual v1/v2 switch or portfolio fuse.

### Corrected BENCH_AB_R2 on $500

| Window | Base $/day | Stress $/day | Stress PnL | Stress return | Stress max DD |
|---|---:|---:|---:|---:|---:|
| Development 2025-05 → 2025-10 | $0.269 | $0.178 | $27.18 | 5.44% | 9.69% |
| Validation 2025-10 → 2026-04 | $0.113 | $0.105 | $19.17 | 3.83% | 2.10% |
| Evaluation 2026-04 → 2026-09 | $0.157 | $0.160 | $24.56 | 4.91% | 0.47% |

The historical +$0.415/day validation and +$0.362/day forward-style figures
remain useful only as provisional high hurdles. They are not verified results
after the Book A fix. The former “forward” report was also a retrospective
replay of already-known history, not prospective paper execution.

## Candidate results

All candidates used eight liquid markets, actual 1m execution, taker fees and
adverse slippage. A level was causal, immutable after publication and could not
use a future pivot or future reclaim candle.

| Candidate | Development stress fills | PF | Mean net R | PnL on $100 | Decision |
|---|---:|---:|---:|---:|---|
| S90 fresh 1h level + distal sweep + full reclaim | 2 | 0.000 | -1.000 | -$0.41 | rejected: sparse and losing |
| S91 fresh 15m level + 1h S/R + full reclaim | 89 | 0.455 | -0.464 | -$6.01 | rejected: no edge |
| S92 S91 + protection from +0.25R | 106 | 0.023 | -0.392 | -$6.05 | rejected: no edge |

S92 produced more fills because early exits freed the global position slot,
but the newly admitted setups were also weak. The higher trade count therefore
did not create an edge.

## What the tests established

- S89's blind resting-limit design was not a reliable baseline: it could use
  already-mitigated zones, duplicate overlapping order blocks and omit gap
  throughs.
- A strong score at zone creation did not predict a profitable first retest.
- Touch count is not used as “strength”; prior touches consume freshness.
- Full 5m reclaim by itself was not enough. In S91, 73 of 89 development
  trades hit the stop and only 16 reached the 2R net target.
- A longer-horizon diagnostic was also weak: the same development entries had
  mean net returns of -0.677% after one day, -0.674% after three days and
  +0.422% after seven days, but the seven-day median was -0.061% and the
  t-statistic only 0.45. That is not sufficient evidence for a momentum-hold
  successor.

## Execution safeguards now covered by regression tests

- pre-publication mitigation is terminal;
- overlap merge does not refresh identity or TTL;
- gap through a zone is observed, not silently skipped;
- first shallow touch consumes S90 freshness;
- reclaim enters on the exact next 1m open;
- a gap that loses the reclaimed edge cancels entry;
- targets solve to 2.0 net-R under stress costs;
- an opposing causal level before target rejects the trade;
- daily and weekly loss anchors use the prior completed minute, not the new
  period's open;
- appended future data do not change an already-created trigger.

## Decision boundary

Profit cannot be made a requirement by changing parameters until a backtest
turns green. That would convert research into curve fitting. A future OB/SR
idea should use genuinely new information (for example order-book absorption
or executed-flow imbalance) and must be frozen before a new, untouched OOS
period. Price-only first-contact/reclaim variants S90–S92 should not be reopened
on these windows.
