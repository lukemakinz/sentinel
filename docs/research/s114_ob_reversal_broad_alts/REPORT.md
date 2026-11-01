# S114 — OB Liquidity Reversal on 48 point-in-time mid-cap alts

Protocol hash: `ce7d23391bf45da3e87aa05ce5b69ac8aa943e30aebb53dd7db7c69d4fc4b4d8`. Symbols simulated: 48; excluded: 0. R per trade, standalone $250 accounts.

| Route | Window | Costs | Trades | WR | PF (R) | Mean R | Total R |
|---|---|---|---:|---:|---:|---:|---:|
| STRICT | development | base | 3 | 0.0% | 0.00 | -0.999 | -3.0 |
| STRICT | development | stress | 3 | 0.0% | 0.00 | -0.999 | -3.0 |
| STRICT | development | severe | 3 | 0.0% | 0.00 | -0.999 | -3.0 |
| STRICT | validation | base | 2 | 50.0% | 1.13 | 0.067 | 0.1 |
| STRICT | validation | stress | 2 | 50.0% | 1.02 | 0.011 | 0.0 |
| STRICT | validation | severe | 2 | 50.0% | 0.87 | -0.064 | -0.1 |
| STRICT | retrospective_evaluation | base | 2 | 0.0% | 0.00 | -0.989 | -2.0 |
| STRICT | retrospective_evaluation | stress | 2 | 0.0% | 0.00 | -0.990 | -2.0 |
| STRICT | retrospective_evaluation | severe | 2 | 0.0% | 0.00 | -0.991 | -2.0 |
| STRICT | POOLED | base | 7 | 14.3% | 0.19 | -0.692 | -4.8 |
| STRICT | POOLED | stress | 7 | 14.3% | 0.17 | -0.708 | -5.0 |
| STRICT | POOLED | severe | 7 | 14.3% | 0.15 | -0.730 | -5.1 |
| EXTERNAL | development | base | 445 | 20.0% | 0.84 | -0.128 | -57.2 |
| EXTERNAL | development | stress | 433 | 19.6% | 0.74 | -0.205 | -88.8 |
| EXTERNAL | development | severe | 416 | 17.8% | 0.60 | -0.331 | -137.5 |
| EXTERNAL | validation | base | 525 | 20.0% | 0.80 | -0.158 | -83.1 |
| EXTERNAL | validation | stress | 502 | 19.1% | 0.69 | -0.253 | -127.0 |
| EXTERNAL | validation | severe | 472 | 18.9% | 0.59 | -0.333 | -157.4 |
| EXTERNAL | retrospective_evaluation | base | 418 | 19.9% | 0.77 | -0.182 | -76.1 |
| EXTERNAL | retrospective_evaluation | stress | 404 | 19.6% | 0.68 | -0.260 | -104.9 |
| EXTERNAL | retrospective_evaluation | severe | 384 | 18.5% | 0.56 | -0.357 | -137.3 |
| EXTERNAL | POOLED | base | 1388 | 20.0% | 0.80 | -0.156 | -216.4 |
| EXTERNAL | POOLED | stress | 1339 | 19.4% | 0.70 | -0.239 | -320.7 |
| EXTERNAL | POOLED | severe | 1272 | 18.4% | 0.58 | -0.340 | -432.2 |
| ABSORB_CVD | development | base | 77 | 23.4% | 1.06 | 0.048 | 3.7 |
| ABSORB_CVD | development | stress | 76 | 23.7% | 1.01 | 0.006 | 0.4 |
| ABSORB_CVD | development | severe | 73 | 20.5% | 0.80 | -0.156 | -11.4 |
| ABSORB_CVD | validation | base | 119 | 21.0% | 0.84 | -0.129 | -15.4 |
| ABSORB_CVD | validation | stress | 114 | 19.3% | 0.69 | -0.251 | -28.7 |
| ABSORB_CVD | validation | severe | 109 | 20.2% | 0.65 | -0.277 | -30.2 |
| ABSORB_CVD | retrospective_evaluation | base | 62 | 27.4% | 1.14 | 0.102 | 6.3 |
| ABSORB_CVD | retrospective_evaluation | stress | 58 | 25.9% | 0.94 | -0.045 | -2.6 |
| ABSORB_CVD | retrospective_evaluation | severe | 53 | 24.5% | 0.80 | -0.150 | -8.0 |
| ABSORB_CVD | POOLED | base | 258 | 23.3% | 0.97 | -0.021 | -5.3 |
| ABSORB_CVD | POOLED | stress | 248 | 22.2% | 0.84 | -0.124 | -30.8 |
| ABSORB_CVD | POOLED | severe | 235 | 21.3% | 0.73 | -0.211 | -49.5 |

- **STRICT: REJECTED** — failed: ['trades', 'profit_factor', 'mean_net_r', 'windows_positive', 'severe_positive', 'symbol_concentration']
- **EXTERNAL: REJECTED** — failed: ['profit_factor', 'mean_net_r', 'windows_positive', 'severe_positive']
- **ABSORB_CVD: REJECTED** — failed: ['profit_factor', 'mean_net_r', 'windows_positive', 'severe_positive']

Retrospective research only; no live approval.
