# S34 — inverse COIN-M fixed-expiry carry

Frozen protocol hash: `77da64055eebae2bf7596943a70a7b1bd985305b21dc5300916330f088212602`.

| Window | Costs | Qualified/decisions | Episodes | WR | PF | Basis PnL | Fees | Slippage | Net | Return | DD | Min collateral | Max lev |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development | base | 0/4 | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $225.00 | 0.000x |
| development | stress | 0/4 | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $225.00 | 0.000x |
| validation | base | 3/4 | 3 | 100.0% | Infinity | $9.69 | $1.62 | $0.27 | $7.81 | 3.122% | 1.183% | $225.00 | 0.972x |
| validation | stress | 3/4 | 3 | 100.0% | Infinity | $9.69 | $2.01 | $1.33 | $6.35 | 2.541% | 1.191% | $225.00 | 0.973x |
| retrospective_evaluation | base | 0/6 | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $225.00 | 0.000x |
| retrospective_evaluation | stress | 0/6 | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $225.00 | 0.000x |
| all_available | base | 3/14 | 3 | 100.0% | Infinity | $9.69 | $1.62 | $0.27 | $7.81 | 3.122% | 1.183% | $225.00 | 0.972x |
| all_available | stress | 3/14 | 3 | 100.0% | Infinity | $9.69 | $2.01 | $1.33 | $6.35 | 2.541% | 1.191% | $225.00 | 0.973x |

Decision: **REJECTED_BY_STRESS_WINDOW_GATE**.

## $25/day check

- base: newest-window average $0.00000/day on $250; linear $25/day capital diagnostic: not applicable.
- stress: newest-window average $0.00000/day on $250; linear $25/day capital diagnostic: not applicable.

The bought coin is also the inverse-futures collateral. Contract notional is always rounded down to whole historical contract sizes, and the residual long-coin fraction is capped. Each episode exits before delivery/roll. The leverage diagnostic uses the continuous contract trade price because historical contract-level liquidation mark and margin tiers are unavailable in this input. A historical pass would authorize paper only.
