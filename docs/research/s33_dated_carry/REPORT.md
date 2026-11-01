# S33 — fixed-expiry cash-and-carry

Frozen protocol hash: `1cc386c3de50f36a842c2eedc9908019011a15180e6d4abe8f9af682657b0304`.

| Window | Costs | Qualified/decisions | Episodes | WR | PF | Basis PnL | Fees | Slippage | Net | Return | DD | Min futures equity | Max futures lev |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development | base | 0/4 | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $175.00 | 0.000x |
| development | stress | 0/4 | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $175.00 | 0.000x |
| validation | base | 3/4 | 3 | 100.0% | Infinity | $2.20 | $0.36 | $0.06 | $1.78 | 0.712% | 0.338% | $163.53 | 0.380x |
| validation | stress | 3/4 | 3 | 100.0% | Infinity | $2.20 | $0.45 | $0.30 | $1.45 | 0.580% | 0.360% | $163.50 | 0.380x |
| retrospective_evaluation | base | 0/6 | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $175.00 | 0.000x |
| retrospective_evaluation | stress | 0/6 | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $175.00 | 0.000x |
| all_available | base | 3/14 | 3 | 100.0% | Infinity | $2.20 | $0.36 | $0.06 | $1.78 | 0.712% | 0.338% | $163.53 | 0.380x |
| all_available | stress | 3/14 | 3 | 100.0% | Infinity | $2.20 | $0.45 | $0.30 | $1.45 | 0.580% | 0.360% | $163.50 | 0.380x |

Decision: **REJECTED_BY_STRESS_WINDOW_GATE**.

## $25/day check

- base: newest-window average $0.00000/day on $250; linear $25/day capital diagnostic: not applicable.
- stress: newest-window average $0.00000/day on $250; linear $25/day capital diagnostic: not applicable.

The position exits one hour before expiry and never crosses a continuous contract roll. Results include distinct spot/futures fills, four fees, adverse slippage and isolated short-collateral diagnostics. H1 history cannot model order-book impact or exact maintenance-margin tiers; a historical pass would authorize paper-forward only.
