# S31 — safer monthly-reset funding carry

Frozen protocol hash: `2254229fd252fefcfff3d81eaa726025fbb5c6db6cadb83ccf5cdc8c6d8e80f2`.

| Window | Costs | Episodes | Funding | Basis PnL | Net | Return | Min futures equity | Max mark leverage | Breaches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development | base | 11 | $22.19 | $-0.25 | $20.14 | 8.054% | $67.51 | 2.581x | 0 |
| development | stress | 11 | $22.18 | $-0.25 | $18.71 | 7.485% | $67.53 | 2.579x | 0 |
| validation | base | 10 | $6.28 | $0.22 | $5.09 | 2.036% | $162.88 | 0.483x | 0 |
| validation | stress | 10 | $6.28 | $0.22 | $3.99 | 1.595% | $162.86 | 0.483x | 0 |
| retrospective_evaluation | base | 8 | $2.35 | $-0.03 | $1.17 | 0.467% | $162.87 | 0.478x | 0 |
| retrospective_evaluation | stress | 8 | $2.34 | $-0.03 | $0.27 | 0.107% | $162.85 | 0.477x | 0 |
| all_available | base | 29 | $30.81 | $-0.07 | $26.39 | 10.555% | $67.51 | 2.581x | 0 |
| all_available | stress | 29 | $30.80 | $-0.07 | $22.96 | 9.184% | $67.53 | 2.579x | 0 |

Decision: **REJECTED_BY_COLLATERAL_BUFFER_GATE**.

## $25/day reality check

- base: the newest retrospective window averaged $0.0015/day on $250; a purely linear $25/day extrapolation is $4,240,955 capital.
- stress: the newest retrospective window averaged $0.0003/day on $250; a purely linear $25/day extrapolation is $18,519,213 capital.

The extrapolation is not a forecast. All periods were already viewed, maintenance tiers are not modelled, and live execution remains disabled. A historical pass permits only a frozen prospective paper test.
