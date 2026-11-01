# S112 — OB Liquidity Reversal

Protocol hash: `6cbbd93e9d5e4d11cc110ea9dcfd1ead2db5ab0874360402e8ade2b3d4dcb7bb`.

Capital $250, risk 0.2% per trade, one position; 1m execution with fees,
slippage and funding. Target for comparison: $5/day.

| Route | Window | Costs | Fills | Clusters | WR | PF | Mean R | PnL | $/day | Gap to $5/day | Max DD |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| STRICT | development | base | 0 | 0 | 0.0% | — | 0.000 | $0.00 | $0.000 | $5.00 | 0.00% |
| STRICT | development | stress | 0 | 0 | 0.0% | — | 0.000 | $0.00 | $0.000 | $5.00 | 0.00% |
| STRICT | development | severe | 0 | 0 | 0.0% | — | 0.000 | $0.00 | $0.000 | $5.00 | 0.00% |
| EXTERNAL | development | base | 53 | 53 | 24.5% | 1.12 | 0.085 | $2.43 | $0.016 | $4.98 | 1.69% |
| EXTERNAL | development | stress | 52 | 52 | 21.2% | 0.82 | -0.139 | $-3.64 | $-0.024 | $5.02 | 3.01% |
| EXTERNAL | development | severe | 48 | 48 | 20.8% | 0.71 | -0.228 | $-5.48 | $-0.036 | $5.04 | 3.20% |

- **STRICT: REJECTED_AT_DEVELOPMENT_GATE** (signals per symbol: {'BTCUSDT': 0, 'ETHUSDT': 0, 'BNBUSDT': 1, 'SOLUSDT': 0, 'XRPUSDT': 0, 'ADAUSDT': 1, 'DOGEUSDT': 1, 'AVAXUSDT': 1}).
- **EXTERNAL: REJECTED_AT_DEVELOPMENT_GATE** (signals per symbol: {'BTCUSDT': 86, 'ETHUSDT': 89, 'BNBUSDT': 118, 'SOLUSDT': 118, 'XRPUSDT': 90, 'ADAUSDT': 110, 'DOGEUSDT': 100, 'AVAXUSDT': 117}).

Retrospective research only; no live approval.
