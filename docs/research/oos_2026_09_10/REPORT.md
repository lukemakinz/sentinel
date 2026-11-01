# OOS 2026-09/10 — frozen BENCH_AB_R2 on untouched data

Protocol hash: `773772ccb98106d874bffd4ddf22f296a9e1a225db5ddfccce69c5d586ab0aba`.

| Window | Costs | A PnL | B PnL (trades) | Total | $/day | Gap to $5/day | Return | Max DD | Sharpe/yr | PSR>0 | DSR (N=133) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| oos_september | base | $15.50 | $5.64 (5) | $21.13 | $0.704 | $4.30 | 4.23% | 1.31% | 3.79 | 0.88 | 0.04 |
| oos_september | stress | $15.34 | $4.37 (5) | $19.71 | $0.657 | $4.34 | 3.94% | 1.36% | 3.54 | 0.86 | 0.04 |
| oos_september | severe | $15.09 | $2.17 (5) | $17.26 | $0.575 | $4.42 | 3.45% | 1.45% | 3.11 | 0.83 | 0.03 |
| oos_full | base | $11.27 | $5.64 (5) | $16.90 | $0.302 | $4.70 | 3.38% | 1.83% | 2.15 | 0.82 | 0.02 |
| oos_full | stress | $11.06 | $4.37 (5) | $15.43 | $0.275 | $4.72 | 3.09% | 1.84% | 1.97 | 0.80 | 0.02 |
| oos_full | severe | $10.72 | $2.17 (5) | $12.89 | $0.230 | $4.77 | 2.58% | 1.86% | 1.66 | 0.75 | 0.02 |

Historical stress $/day: development 0.178, validation 0.105, retrospective evaluation 0.160.

**Decision: CONSISTENT_PROCEED_TO_DAILY_PAPER_FORWARD.**

56 days can falsify but not prove an edge. Untouched-data replay, not live.
