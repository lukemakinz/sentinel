# S98 — independent dual momentum

Protocol hash: `fa1a9933a09ed58045a9c60218be2d9ba038a4cd73299ec290db4e50286f8af1`.

All periods are contaminated historical diagnostics, not true OOS.

| Period | Costs | PnL | Return | $/day | DD | Sharpe | Positive months |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | base | $128.26 | 25.65% | $0.352 | 15.07% | 1.34 | 50.0% |
| development | stress | $125.25 | 25.05% | $0.344 | 15.25% | 1.31 | 50.0% |
| development | severe | $121.75 | 24.35% | $0.334 | 15.46% | 1.28 | 50.0% |
| validation | base | $297.91 | 47.42% | $0.803 | 14.23% | 2.14 | 69.2% |
| validation | stress | $290.64 | 46.48% | $0.783 | 14.48% | 2.11 | 69.2% |
| validation | severe | $282.28 | 45.40% | $0.761 | 14.77% | 2.07 | 61.5% |
| retrospective_evaluation | base | $9.30 | 1.00% | $0.015 | 13.16% | 0.11 | 40.0% |
| retrospective_evaluation | stress | $4.31 | 0.47% | $0.007 | 13.28% | 0.09 | 40.0% |
| retrospective_evaluation | severe | $-1.36 | -0.15% | $-0.002 | 13.41% | 0.06 | 40.0% |

## Full continuous replay

| Costs | PnL | Return | DD | Sharpe | Funding | Fees | Slippage |
|---|---:|---:|---:|---:|---:|---:|---:|
| base | $435.47 | 87.09% | 15.07% | 1.11 | $-15.28 | $10.48 | $4.19 |
| stress | $420.19 | 84.04% | 15.25% | 1.08 | $-15.11 | $16.61 | $10.38 |
| severe | $402.68 | 80.54% | 15.46% | 1.05 | $-14.92 | $20.55 | $20.55 |

## Frozen robustness checks

- Momentum neighbors, stress PnL: `{'63': 402.65530137307235, '126': 529.720047768114}`.
- Rebalance phases, stress PnL: `{'wednesday': 387.8160107356101, 'friday': 292.9257623400848}`.
- Leave-one-symbol-out, stress PnL: `{'BTCUSDT': 342.01503039026045, 'ETHUSDT': 326.6381621639473, 'SOLUSDT': 365.92837272651786, 'BNBUSDT': 190.52215723873394, 'XRPUSDT': 347.6337841334572, 'DOGEUSDT': 364.9447175438579}`.
- 28-day block bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': 87.12942770548774, 'p50_terminal_pnl': 407.20239245128164, 'p90_terminal_pnl': 968.782115683469, 'observed_terminal_pnl': 420.191559628033}`.

**Decision: REJECTED_AT_HISTORICAL_GATE.**

A pass authorizes paper-forward observation only; it is not proof of future profit.
