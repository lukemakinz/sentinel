# S32 XFRD — Binance/Bybit funding dispersion + basis

Frozen protocol hash: `80fa490404fbb9e5daea8377eebca73a9eaa3b2fd49d2be03a43c59820781032`.

| Window | Costs | Episodes | WR | PF | Funding | Basis PnL | Fees | Slippage | Funding-cost | Net | Return | DD | Min venue equity | Max venue lev |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development | base | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $100.00 | 0.000x |
| development | stress | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $100.00 | 0.000x |
| validation | base | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $100.00 | 0.000x |
| validation | stress | 0 | 0.0% | None | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 | 0.000% | 0.000% | $100.00 | 0.000x |
| retrospective_evaluation | base | 1 | 100.0% | Infinity | $0.11 | $0.21 | $0.04 | $0.02 | $0.04 | $0.25 | 0.099% | 0.030% | $84.85 | 0.617x |
| retrospective_evaluation | stress | 1 | 100.0% | Infinity | $0.11 | $0.21 | $0.11 | $0.11 | $-0.11 | $0.09 | 0.037% | 0.058% | $84.80 | 0.617x |
| all_available | base | 1 | 100.0% | Infinity | $0.11 | $0.21 | $0.04 | $0.02 | $0.04 | $0.25 | 0.099% | 0.030% | $84.85 | 0.617x |
| all_available | stress | 1 | 100.0% | Infinity | $0.11 | $0.21 | $0.11 | $0.11 | $-0.11 | $0.09 | 0.037% | 0.058% | $84.80 | 0.617x |

Decision: **REJECTED_BY_STRESS_NET_WINDOW_GATE**.

## $25/day check

- base: newest window average $0.00041/day on $250; linear $25/day capital diagnostic: $15,349,488.
- stress: newest window average $0.00015/day on $250; linear $25/day capital diagnostic: $41,027,069.

This is an H1 retrospective replay. It separately accounts for both venue balances, realized funding, cross-venue basis PnL, fees, adverse slippage and venue mark leverage. It cannot model order-book queue, partial one-leg fills, API outages, ADL or withdrawal freezes. Even a historical pass authorizes paper-forward only.
