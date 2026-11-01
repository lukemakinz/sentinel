# H1 Trend Pullback v1

Protocol hash: `275d1de19e58b087f83175569fb884a131a3d7bb1104d9453166ebabe4298830`.

**Retrospective diagnostic only. Live remains disabled.**

| Window | Costs | Raw candidates | Fills | WR | PF | Mean R | PnL | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| development | base | 16 | 8 | 50.0% | 1.2286536116415296 | 0.114 | $0.46 | 0.53% |
| development | stress | 16 | 3 | 33.3% | 0.5661770456634749 | -0.289 | $-0.43 | 0.40% |
| development | severe | 16 | 0 | 0.0% | None | 0.000 | $0.00 | 0.00% |

**Decision: REJECTED_AT_DEVELOPMENT_STRESS_GATE.**

H1 is evaluated first with static P0. P1/P2 are not allowed to rescue an entry stream that has no positive edge under P0.
