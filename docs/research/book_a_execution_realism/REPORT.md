# Book A execution realism — funding and KuCoin contract sizes

Protocol hash: `cd76066cde5a46fe9ef0a42fa0ff935395011bd4b34fa8a451e25ad748ed1475`. Stress costs, rules unchanged.

| Window | Variant | Capital | PnL | Return | $/day | $/day per $250 | Funding paid | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| development | V0_frozen | $250 | $90.96 | 36.39% | $0.595 | $0.595 | $0.00 | 6.88% |
| development | V1_binance_funding | $250 | $91.08 | 36.43% | $0.595 | $0.595 | $1.73 | 6.91% |
| development | V2_kucoin_funding | $250 | $89.98 | 35.99% | $0.588 | $0.588 | $2.76 | 6.93% |
| development | V3_kucoin_250 | $250 | $86.80 | 34.72% | $0.567 | $0.567 | $2.69 | 7.03% |
| development | V4_kucoin_500 | $500 | $177.18 | 35.44% | $1.158 | $0.579 | $6.13 | 7.49% |
| development | V5_kucoin_1000 | $1000 | $326.52 | 32.65% | $2.134 | $0.534 | $11.48 | 6.75% |
| validation | V0_frozen | $250 | $9.76 | 3.91% | $0.054 | $0.054 | $0.00 | 5.80% |
| validation | V1_binance_funding | $250 | $9.75 | 3.90% | $0.054 | $0.054 | $0.01 | 5.80% |
| validation | V2_kucoin_funding | $250 | $9.75 | 3.90% | $0.054 | $0.054 | $0.02 | 5.80% |
| validation | V3_kucoin_250 | $250 | $9.22 | 3.69% | $0.051 | $0.051 | $0.02 | 5.50% |
| validation | V4_kucoin_500 | $500 | $19.76 | 3.95% | $0.109 | $0.054 | $0.04 | 5.88% |
| validation | V5_kucoin_1000 | $1000 | $39.52 | 3.95% | $0.217 | $0.054 | $0.07 | 5.88% |
| retrospective_evaluation | V0_frozen | $250 | $0.32 | 0.13% | $0.002 | $0.002 | $0.00 | 1.04% |
| retrospective_evaluation | V1_binance_funding | $250 | $0.30 | 0.12% | $0.002 | $0.002 | $0.02 | 1.04% |
| retrospective_evaluation | V2_kucoin_funding | $250 | $0.28 | 0.11% | $0.002 | $0.002 | $0.04 | 1.04% |
| retrospective_evaluation | V3_kucoin_250 | $250 | $0.41 | 0.16% | $0.003 | $0.003 | $0.04 | 1.02% |
| retrospective_evaluation | V4_kucoin_500 | $500 | $-5.14 | -1.03% | $-0.034 | $-0.017 | $0.21 | 1.89% |
| retrospective_evaluation | V5_kucoin_1000 | $1000 | $-11.77 | -1.18% | $-0.077 | $-0.019 | $0.43 | 1.96% |
| oos_2026_09_10 | V0_frozen | $250 | $11.06 | 4.42% | $0.197 | $0.197 | $0.00 | 3.58% |
| oos_2026_09_10 | V1_binance_funding | $250 | $10.70 | 4.28% | $0.191 | $0.191 | $0.36 | 3.64% |
| oos_2026_09_10 | V2_kucoin_funding | $250 | $10.48 | 4.19% | $0.187 | $0.187 | $0.58 | 3.68% |
| oos_2026_09_10 | V3_kucoin_250 | $250 | $10.62 | 4.25% | $0.190 | $0.190 | $0.56 | 3.42% |
| oos_2026_09_10 | V4_kucoin_500 | $500 | $15.94 | 3.19% | $0.285 | $0.142 | $1.31 | 4.51% |
| oos_2026_09_10 | V5_kucoin_1000 | $1000 | $28.75 | 2.87% | $0.513 | $0.128 | $2.68 | 4.42% |

## Book B (BTC, $6 fixed risk) vs 0.001 BTC contracts

| Window | Trades | Median contracts | Min | Median size error | Max error | Median notional |
|---|---:|---:|---:|---:|---:|---:|
| development | 58 | 2.3 | 2.1 | 12.0% | 19.9% | $270 |
| validation | 8 | 2.5 | 2.5 | 17.7% | 19.9% | $311 |
| retrospective_evaluation | 1 | 4.4 | 4.4 | 8.4% | 8.4% | $312 |
| oos_2026_09_10 | 5 | 3.9 | 3.9 | 2.1% | 3.6% | $312 |

KuCoin funding = Binance x1.6 (30-day ratio, sensitivity only).
