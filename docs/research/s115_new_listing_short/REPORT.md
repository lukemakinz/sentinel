# S115 — short new Binance USD-M listings

Protocol: `protocol.json` (frozen 2026-11-01 before results). 663 listings with a
first daily bar in 2023-01-01 … 2026-08-01, including later-delisted symbols.
Funding data present for every trade.

## Result (stress costs: 5 bps fee + 30 bps slippage per side, actual funding)

| | trades | mean net | median net | WR | 97.5% CI (mean) | funding | stop rate | BTC-hedged mean | worst |
|---|---|---|---|---|---|---|---|---|---|
| S115_A (day 2 → 14d, stop +35%) | 663 | **+1.54%** | +4.05% | 56% | −1.35% … +4.41% | −0.78% | 30% | +1.83% | −72.5% |
| S115_B (day 4 → 30d, stop +50%) | 663 | **+1.76%** | +6.84% | 59% | −2.75% … +6.60% | −0.34% | 27% | +3.77% | −77.9% |

Mean net by listing year (stress):

| | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| S115_A | +0.28% | **−1.87%** | +3.47% | +2.07% |
| S115_B | **−1.33%** | +1.72% | +4.60% | **−0.18%** |

## Decision: **REJECTED** (both)

Failed gates: CI lower bound ≤ 0 and not every year positive. BTC-hedged gate passed.

## What the data says

* The typical new listing does drift down (median +4–7% for the short, 56–59% wins),
  and the effect is not just alt beta (hedged mean is higher than unhedged).
* The mean is destroyed by squeeze tails. The worst losses are **funding**, not
  price gaps: FUNUSDT paid −36.7% funding in 5 days on top of the −35.7% stop;
  55 trades paid more than 5% funding. Shorts of hyped listings are crowded and
  pay for it.
* Exposure is unmanageable as specified: up to 43 (A) / 68 (B) concurrent shorts.

## Follow-up (must be a new protocol, and is post-hoc motivated)

A funding-aware variant (skip entry or exit when funding is deeply negative) is
the obvious next idea, but it was motivated by looking at this full-period
result. It therefore cannot be validated on 2023-2026 history; it would need a
fresh paper-forward on new listings. Expected value is uncertain.
