# S7 — scalping research

Data: 2025-12-01 → 2026-04-01 (UTC, end exclusive).
Train: 2025-12-03 → 2026-02-01; validation → 2026-03-01; holdout → 2026-04-01.

Selected before holdout: **S7_reclaim_15m_3of5**. Validation criteria met: **False**.

Each pair starts with $10,000 per phase; risk 0.25% including estimated stop costs, notional ≤ equity.
Fees 5 bps/side, adverse slippage 2 bps/side (stress: 5), actual funding with minute-price proxy.
Frequency includes all calendar days, including days with no entries. No live approval inferred.

| Phase | Variant | Pair | Trades | /day | Days ≥3 | Win % | PF | Net % | MTM DD % |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| train | S7_reclaim_5m_3of5 | BTCUSDT | 4 | 0.07 | 0.0% | 75.0 | 1.87 | 0.22 | 0.30 |
| train | S7_reclaim_5m_3of5 | ETHUSDT | 3 | 0.05 | 0.0% | 0.0 | 0.00 | -0.51 | 0.63 |
| train | S7_reclaim_5m_3of5 | SOLUSDT | 6 | 0.10 | 0.0% | 50.0 | 0.77 | -0.17 | 0.66 |
| train | S7_reclaim_5m_3of5 | BNBUSDT | 4 | 0.07 | 0.0% | 25.0 | 0.08 | -0.59 | 0.77 |
| train | S7_reclaim_15m_3of5 | BTCUSDT | 0 | 0.00 | 0.0% | 0.0 | n/a | 0.00 | 0.00 |
| train | S7_reclaim_15m_3of5 | ETHUSDT | 1 | 0.02 | 0.0% | 0.0 | 0.00 | -0.25 | 0.34 |
| train | S7_reclaim_15m_3of5 | SOLUSDT | 1 | 0.02 | 0.0% | 0.0 | 0.00 | -0.25 | 0.25 |
| train | S7_reclaim_15m_3of5 | BNBUSDT | 4 | 0.07 | 0.0% | 25.0 | 0.08 | -0.69 | 0.69 |
| train | S7_hybrid_5m_3of5 | BTCUSDT | 210 | 3.50 | 61.7% | 37.1 | 0.51 | -11.89 | 13.34 |
| train | S7_hybrid_5m_3of5 | ETHUSDT | 306 | 5.10 | 73.3% | 35.9 | 0.50 | -18.74 | 20.36 |
| train | S7_hybrid_5m_3of5 | SOLUSDT | 255 | 4.25 | 63.3% | 31.8 | 0.40 | -20.55 | 21.13 |
| train | S7_hybrid_5m_3of5 | BNBUSDT | 172 | 2.87 | 53.3% | 34.9 | 0.45 | -11.86 | 13.56 |
| train | S7_hybrid_5m_2of5 | BTCUSDT | 210 | 3.50 | 61.7% | 37.1 | 0.51 | -11.89 | 13.34 |
| train | S7_hybrid_5m_2of5 | ETHUSDT | 309 | 5.15 | 75.0% | 36.6 | 0.51 | -18.35 | 19.97 |
| train | S7_hybrid_5m_2of5 | SOLUSDT | 260 | 4.33 | 65.0% | 31.5 | 0.39 | -21.41 | 21.98 |
| train | S7_hybrid_5m_2of5 | BNBUSDT | 174 | 2.90 | 53.3% | 35.6 | 0.46 | -11.71 | 13.42 |
| train | S7_hybrid_5m_4of5 | BTCUSDT | 192 | 3.20 | 58.3% | 36.5 | 0.49 | -11.69 | 13.40 |
| train | S7_hybrid_5m_4of5 | ETHUSDT | 291 | 4.85 | 71.7% | 36.1 | 0.50 | -17.94 | 19.46 |
| train | S7_hybrid_5m_4of5 | SOLUSDT | 229 | 3.82 | 61.7% | 33.2 | 0.44 | -16.93 | 17.91 |
| train | S7_hybrid_5m_4of5 | BNBUSDT | 164 | 2.73 | 50.0% | 34.1 | 0.43 | -11.70 | 13.34 |
| train | S7_hybrid_15m_3of5 | BTCUSDT | 172 | 2.87 | 55.0% | 30.2 | 0.36 | -11.39 | 12.12 |
| train | S7_hybrid_15m_3of5 | ETHUSDT | 195 | 3.25 | 60.0% | 33.8 | 0.56 | -8.35 | 9.02 |
| train | S7_hybrid_15m_3of5 | SOLUSDT | 154 | 2.57 | 51.7% | 30.5 | 0.40 | -11.15 | 11.94 |
| train | S7_hybrid_15m_3of5 | BNBUSDT | 158 | 2.63 | 48.3% | 29.7 | 0.34 | -11.53 | 12.70 |
| train | S7_hybrid_5m_fixed_exit | BTCUSDT | 207 | 3.45 | 61.7% | 33.8 | 0.51 | -12.04 | 13.73 |
| train | S7_hybrid_5m_fixed_exit | ETHUSDT | 300 | 5.00 | 73.3% | 32.3 | 0.45 | -20.33 | 21.70 |
| train | S7_hybrid_5m_fixed_exit | SOLUSDT | 251 | 4.18 | 63.3% | 28.7 | 0.39 | -20.71 | 21.29 |
| train | S7_hybrid_5m_fixed_exit | BNBUSDT | 172 | 2.87 | 53.3% | 33.7 | 0.43 | -12.19 | 13.76 |
| train | control_momentum_5m_3of5 | BTCUSDT | 340 | 5.67 | 76.7% | 35.9 | 0.42 | -22.82 | 23.71 |
| train | control_momentum_5m_3of5 | ETHUSDT | 479 | 7.98 | 91.7% | 37.6 | 0.54 | -25.04 | 27.26 |
| train | control_momentum_5m_3of5 | SOLUSDT | 512 | 8.53 | 100.0% | 33.0 | 0.41 | -35.29 | 35.96 |
| train | control_momentum_5m_3of5 | BNBUSDT | 369 | 6.15 | 88.3% | 35.8 | 0.42 | -25.10 | 26.55 |
| train | control_momentum_5m_4of5 | BTCUSDT | 312 | 5.20 | 75.0% | 35.3 | 0.41 | -21.91 | 23.00 |
| train | control_momentum_5m_4of5 | ETHUSDT | 460 | 7.67 | 91.7% | 37.4 | 0.53 | -24.56 | 26.83 |
| train | control_momentum_5m_4of5 | SOLUSDT | 496 | 8.27 | 98.3% | 33.9 | 0.43 | -33.30 | 33.98 |
| train | control_momentum_5m_4of5 | BNBUSDT | 349 | 5.82 | 88.3% | 36.1 | 0.43 | -23.35 | 24.87 |
| validation | S7_reclaim_5m_3of5 | BTCUSDT | 3 | 0.11 | 0.0% | 33.3 | 0.53 | -0.23 | 0.55 |
| validation | S7_reclaim_5m_3of5 | ETHUSDT | 4 | 0.14 | 0.0% | 25.0 | 0.56 | -0.22 | 0.55 |
| validation | S7_reclaim_5m_3of5 | SOLUSDT | 2 | 0.07 | 0.0% | 0.0 | 0.00 | -0.25 | 0.44 |
| validation | S7_reclaim_5m_3of5 | BNBUSDT | 3 | 0.11 | 0.0% | 66.7 | 1.23 | 0.06 | 0.41 |
| validation | S7_reclaim_15m_3of5 | BTCUSDT | 0 | 0.00 | 0.0% | 0.0 | n/a | 0.00 | 0.00 |
| validation | S7_reclaim_15m_3of5 | ETHUSDT | 1 | 0.04 | 0.0% | 0.0 | 0.00 | -0.25 | 0.33 |
| validation | S7_reclaim_15m_3of5 | SOLUSDT | 0 | 0.00 | 0.0% | 0.0 | n/a | 0.00 | 0.00 |
| validation | S7_reclaim_15m_3of5 | BNBUSDT | 0 | 0.00 | 0.0% | 0.0 | n/a | 0.00 | 0.00 |
| validation | S7_hybrid_5m_3of5 | BTCUSDT | 151 | 5.39 | 67.9% | 33.1 | 0.46 | -11.30 | 11.66 |
| validation | S7_hybrid_5m_3of5 | ETHUSDT | 176 | 6.29 | 75.0% | 38.1 | 0.64 | -8.47 | 10.40 |
| validation | S7_hybrid_5m_3of5 | SOLUSDT | 171 | 6.11 | 75.0% | 34.5 | 0.55 | -10.61 | 11.36 |
| validation | S7_hybrid_5m_3of5 | BNBUSDT | 147 | 5.25 | 67.9% | 41.5 | 0.66 | -6.61 | 7.40 |
| validation | S7_hybrid_5m_2of5 | BTCUSDT | 152 | 5.43 | 67.9% | 32.9 | 0.46 | -11.52 | 11.88 |
| validation | S7_hybrid_5m_2of5 | ETHUSDT | 178 | 6.36 | 75.0% | 38.2 | 0.64 | -8.42 | 10.37 |
| validation | S7_hybrid_5m_2of5 | SOLUSDT | 176 | 6.29 | 78.6% | 34.1 | 0.53 | -11.39 | 11.91 |
| validation | S7_hybrid_5m_2of5 | BNBUSDT | 148 | 5.29 | 67.9% | 41.9 | 0.68 | -6.25 | 7.05 |
| validation | S7_hybrid_5m_4of5 | BTCUSDT | 139 | 4.96 | 67.9% | 34.5 | 0.48 | -9.93 | 10.29 |
| validation | S7_hybrid_5m_4of5 | ETHUSDT | 162 | 5.79 | 75.0% | 38.9 | 0.68 | -6.60 | 9.32 |
| validation | S7_hybrid_5m_4of5 | SOLUSDT | 159 | 5.68 | 75.0% | 35.8 | 0.60 | -8.49 | 9.20 |
| validation | S7_hybrid_5m_4of5 | BNBUSDT | 138 | 4.93 | 67.9% | 42.0 | 0.68 | -5.76 | 6.79 |
| validation | S7_hybrid_15m_3of5 | BTCUSDT | 83 | 2.96 | 53.6% | 38.6 | 0.73 | -2.31 | 3.31 |
| validation | S7_hybrid_15m_3of5 | ETHUSDT | 88 | 3.14 | 60.7% | 39.8 | 0.90 | -0.86 | 2.99 |
| validation | S7_hybrid_15m_3of5 | SOLUSDT | 89 | 3.18 | 57.1% | 41.6 | 0.71 | -2.55 | 3.60 |
| validation | S7_hybrid_15m_3of5 | BNBUSDT | 80 | 2.86 | 46.4% | 36.2 | 0.52 | -4.37 | 4.79 |
| validation | S7_hybrid_5m_fixed_exit | BTCUSDT | 151 | 5.39 | 67.9% | 32.5 | 0.47 | -11.17 | 11.48 |
| validation | S7_hybrid_5m_fixed_exit | ETHUSDT | 170 | 6.07 | 75.0% | 37.6 | 0.70 | -6.73 | 9.06 |
| validation | S7_hybrid_5m_fixed_exit | SOLUSDT | 171 | 6.11 | 75.0% | 32.2 | 0.55 | -10.58 | 11.38 |
| validation | S7_hybrid_5m_fixed_exit | BNBUSDT | 144 | 5.14 | 67.9% | 38.9 | 0.63 | -6.86 | 7.37 |
| validation | control_momentum_5m_3of5 | BTCUSDT | 252 | 9.00 | 100.0% | 32.1 | 0.41 | -19.57 | 19.67 |
| validation | control_momentum_5m_3of5 | ETHUSDT | 285 | 10.18 | 100.0% | 38.6 | 0.58 | -15.23 | 17.37 |
| validation | control_momentum_5m_3of5 | SOLUSDT | 277 | 9.89 | 100.0% | 35.7 | 0.55 | -15.62 | 16.24 |
| validation | control_momentum_5m_3of5 | BNBUSDT | 255 | 9.11 | 100.0% | 39.6 | 0.59 | -13.46 | 14.75 |
| validation | control_momentum_5m_4of5 | BTCUSDT | 238 | 8.50 | 100.0% | 32.4 | 0.41 | -18.68 | 18.91 |
| validation | control_momentum_5m_4of5 | ETHUSDT | 260 | 9.29 | 100.0% | 39.2 | 0.61 | -12.93 | 15.81 |
| validation | control_momentum_5m_4of5 | SOLUSDT | 267 | 9.54 | 100.0% | 36.7 | 0.59 | -13.80 | 14.64 |
| validation | control_momentum_5m_4of5 | BNBUSDT | 244 | 8.71 | 96.4% | 39.8 | 0.59 | -12.89 | 13.59 |
| holdout | S7_reclaim_5m_3of5 | BTCUSDT | 1 | 0.03 | 0.0% | 0.0 | 0.00 | -0.25 | 0.31 |
| holdout | S7_reclaim_5m_3of5 | ETHUSDT | 5 | 0.16 | 0.0% | 20.0 | 0.35 | -0.56 | 0.89 |
| holdout | S7_reclaim_5m_3of5 | SOLUSDT | 2 | 0.06 | 0.0% | 0.0 | 0.00 | -0.50 | 0.50 |
| holdout | S7_reclaim_5m_3of5 | BNBUSDT | 0 | 0.00 | 0.0% | 0.0 | n/a | 0.00 | 0.00 |
| holdout | S7_reclaim_15m_3of5 | BTCUSDT | 1 | 0.03 | 0.0% | 100.0 | n/a | 0.31 | 0.19 |
| holdout | S7_reclaim_15m_3of5 | ETHUSDT | 1 | 0.03 | 0.0% | 100.0 | n/a | 0.04 | 0.13 |
| holdout | S7_reclaim_15m_3of5 | SOLUSDT | 1 | 0.03 | 0.0% | 100.0 | n/a | 0.23 | 0.26 |
| holdout | S7_reclaim_15m_3of5 | BNBUSDT | 0 | 0.00 | 0.0% | 0.0 | n/a | 0.00 | 0.00 |
| holdout_stress | S7_reclaim_15m_3of5 | BTCUSDT | 1 | 0.03 | 0.0% | 100.0 | n/a | 0.30 | 0.20 |
| holdout_stress | S7_reclaim_15m_3of5 | ETHUSDT | 1 | 0.03 | 0.0% | 100.0 | n/a | 0.02 | 0.13 |
| holdout_stress | S7_reclaim_15m_3of5 | SOLUSDT | 1 | 0.03 | 0.0% | 100.0 | n/a | 0.16 | 0.24 |
| holdout_stress | S7_reclaim_15m_3of5 | BNBUSDT | 0 | 0.00 | 0.0% | 0.0 | n/a | 0.00 | 0.00 |
| holdout | control_momentum_5m_3of5 | BTCUSDT | 263 | 8.48 | 100.0% | 38.0 | 0.54 | -15.06 | 15.35 |
| holdout | control_momentum_5m_3of5 | ETHUSDT | 288 | 9.29 | 100.0% | 37.5 | 0.58 | -14.85 | 15.17 |
| holdout | control_momentum_5m_3of5 | SOLUSDT | 297 | 9.58 | 100.0% | 36.7 | 0.49 | -19.22 | 19.37 |
| holdout | control_momentum_5m_3of5 | BNBUSDT | 226 | 7.29 | 93.5% | 34.5 | 0.43 | -15.83 | 16.35 |

## Limits

- Profile approximated from 1m typical price weighted by volume (48 bins).
- 1m intrabar ordering unknown: old stop takes precedence over targets.
- No queue, latency, exchange quantity rounding, or order rejection model.
- Independent accounts per pair, not a combined correlated portfolio.
- No live deployment; target frequency is assessed, never enforced.

Sources: [Binance public data](https://github.com/binance/binance-public-data), [archive](https://data.binance.vision/). Archive URLs and verified SHA256 in data_manifest.json.
