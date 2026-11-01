# H3 Double Sweep Divergence v1

Protocol hash: `3edffd6752985f69ad8c1d9c602ddbb4bda91090183a961927fa1c8a04f9c9e6`.

**Retrospective diagnostic only. Live remains disabled.**

| Window | Costs | Raw candidates | Fills | WR | PF | Mean R | PnL | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| development | base | 5 | 1 | 100.0% | Infinity | 1.186 | $0.59 | 0.11% |
| development | stress | 5 | 0 | 0.0% | None | 0.000 | $0.00 | 0.00% |
| development | severe | 5 | 0 | 0.0% | None | 0.000 | $0.00 | 0.00% |

**Decision: REJECTED_AT_DEVELOPMENT_STRESS_GATE.**

This tests the full mechanism as one frozen hypothesis: controlled second sweep, regular RSI divergence, range regime, neckline break and limit retest. A failed gate closes v1; no threshold search is permitted.

## Failure diagnosis

- Development produced only 5 raw candidates across eight symbols, versus the preregistered minimum of 40 fills.
- Base execution filled 1: 2 limits expired and 2 candidates failed the economics gate.
- Under stress costs, 3 candidates failed economics and 2 limits expired; no position was opened.
- The sole base-cost fill reached its 1.5R target (+1.186 net R), but one observation cannot establish expectancy. This is a useful case study, not evidence for promotion.

This side hypothesis does not replace the preregistered Intraday v2 H3 failed-auction route, which additionally requires executed-flow/absorption confirmation.
