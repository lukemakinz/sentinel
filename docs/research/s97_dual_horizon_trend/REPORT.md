# S97 — dual-horizon trend with funding-crowding veto

Protocol hash: `b260e0dceeba431112c1d4a5213390fc0028f714fe7cee3962f3d697220c9bc9`.

All periods are contaminated historical diagnostics, not true OOS.

| Period | Costs | PnL | Return | $/day | DD | Sharpe | Positive months |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | base | $189.39 | 37.88% | $0.520 | 16.61% | 1.50 | 58.3% |
| development | stress | $177.99 | 35.60% | $0.489 | 16.87% | 1.43 | 50.0% |
| development | severe | $164.91 | 32.98% | $0.453 | 17.16% | 1.35 | 50.0% |
| validation | base | $83.77 | 12.15% | $0.226 | 22.95% | 0.68 | 30.8% |
| validation | stress | $74.45 | 10.98% | $0.201 | 23.40% | 0.62 | 30.8% |
| validation | severe | $64.03 | 9.63% | $0.173 | 23.92% | 0.56 | 30.8% |
| retrospective_evaluation | base | $69.23 | 8.95% | $0.115 | 31.75% | 0.33 | 55.0% |
| retrospective_evaluation | stress | $53.72 | 7.14% | $0.089 | 32.06% | 0.29 | 55.0% |
| retrospective_evaluation | severe | $36.87 | 5.06% | $0.061 | 32.41% | 0.25 | 50.0% |

## Full continuous replay

| Costs | PnL | Return | DD | Sharpe | Funding | Fees | Slippage |
|---|---:|---:|---:|---:|---:|---:|---:|
| base | $342.39 | 68.48% | 31.75% | 0.72 | $-1.94 | $27.70 | $11.08 |
| stress | $306.15 | 61.23% | 32.06% | 0.67 | $-1.97 | $43.26 | $27.03 |
| severe | $265.81 | 53.16% | 32.41% | 0.61 | $-2.00 | $52.56 | $52.56 |

## Frozen robustness checks

- Neighbor horizons, stress PnL: `{'21_84': -212.49031684172337, '35_140': -37.7273701371592}`.
- Leave-one-symbol-out, stress PnL: `{'BTCUSDT': 276.4450863643317, 'ETHUSDT': 141.487153242761, 'SOLUSDT': 264.6877798846573, 'BNBUSDT': 67.72095263366577, 'XRPUSDT': 334.7307079781293, 'DOGEUSDT': 138.85212404018785}`.
- 28-day block bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': -112.0772239845318, 'p50_terminal_pnl': 318.2590382096489, 'p90_terminal_pnl': 1088.9304212048633, 'observed_terminal_pnl': 306.1534043849333}`.

**Decision: REJECTED_AT_HISTORICAL_GATE.**

A historical pass authorizes only prospective paper-forward observation; live trading remains disabled.
