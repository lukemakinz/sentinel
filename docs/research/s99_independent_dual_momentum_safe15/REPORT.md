# S99 — independent dual momentum, safe 15% vol

Protocol hash: `3cb21e1f942f2ede0f274a6e413ba23c22a1ea3c59e720602b7d6d6627bee9a1`.

Risk-only repair of S98. All periods are contaminated historical diagnostics.

| Period | Costs | PnL | Return | $/day | DD | Sharpe | Positive months |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | base | $95.22 | 19.04% | $0.262 | 11.47% | 1.33 | 50.0% |
| development | stress | $93.03 | 18.61% | $0.256 | 11.61% | 1.30 | 50.0% |
| development | severe | $90.48 | 18.10% | $0.249 | 11.77% | 1.27 | 50.0% |
| validation | base | $208.47 | 35.02% | $0.562 | 10.80% | 2.16 | 69.2% |
| validation | stress | $203.82 | 34.37% | $0.549 | 10.99% | 2.13 | 69.2% |
| validation | severe | $198.45 | 33.61% | $0.535 | 11.22% | 2.09 | 61.5% |
| retrospective_evaluation | base | $14.29 | 1.78% | $0.024 | 10.01% | 0.15 | 45.0% |
| retrospective_evaluation | stress | $10.83 | 1.36% | $0.018 | 10.10% | 0.13 | 45.0% |
| retrospective_evaluation | severe | $6.89 | 0.87% | $0.011 | 10.20% | 0.10 | 45.0% |

## Full continuous replay

| Costs | PnL | Return | DD | Sharpe | Funding | Fees | Slippage |
|---|---:|---:|---:|---:|---:|---:|---:|
| base | $317.97 | 63.59% | 11.47% | 1.13 | $-10.49 | $7.29 | $2.92 |
| stress | $307.68 | 61.54% | 11.61% | 1.10 | $-10.41 | $11.59 | $7.24 |
| severe | $295.82 | 59.16% | 11.77% | 1.07 | $-10.31 | $14.37 | $14.37 |

## Frozen robustness checks

- Vol-target neighbors: `{'0.125': {'net_pnl': 249.27359074486174, 'max_drawdown_pct': 9.750620467882632}, '0.175': {'net_pnl': 365.50388213244423, 'max_drawdown_pct': 13.444795681585099}}`.
- Momentum neighbors: `{'63': 296.712971869644, '126': 380.48058880708743}`.
- Rebalance phases: `{'wednesday': 277.93725775400844, 'friday': 218.3307183389917}`.
- Leave-one-symbol-out: `{'BTCUSDT': 246.5105074648875, 'ETHUSDT': 244.98567607285815, 'SOLUSDT': 285.8283197337421, 'BNBUSDT': 144.7227328530662, 'XRPUSDT': 259.6825343100745, 'DOGEUSDT': 270.34033689165267}`.
- 28-day block bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': 73.31786322147323, 'p50_terminal_pnl': 299.0518635637969, 'p90_terminal_pnl': 653.8799602998729, 'observed_terminal_pnl': 307.6769377904152}`.

**Decision: HISTORICAL_GATE_PASSED_PAPER_FORWARD_ONLY.**

Historical passage authorizes only a prospective paper challenger, never a profit guarantee.
