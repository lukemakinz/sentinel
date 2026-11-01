# S110 — S108 wider-universe scalability test

Protocol hash: `2dd89884ef61758e5876d746ae6e12379dc4e0601e95caf02b1550c334bd63f7`.

**Selection-contaminated historical diagnostic. Live remains disabled.**

No signal, regime, risk or execution parameter from S108 was changed. Only six predeclared markets were added.

| Universe | Costs | Signals | Trades | Long/short | PF | PnL | $/month | DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| original_control | base | 9 | 8 | - | 3.8303377121058007 | $2.12 | $0.12 | 0.19% |
| original_control | stress | 9 | 8 | 2/6 | 3.1331481102869208 | $1.60 | $0.09 | 0.18% |
| original_control | severe | 9 | 8 | - | 2.5261677120721338 | $1.14 | $0.07 | 0.18% |
| extension | base | 6 | 6 | - | 0.022106142586745935 | $-1.22 | $-0.07 | 0.29% |
| extension | stress | 6 | 6 | 0/6 | 0.0069189497632608015 | $-1.24 | $-0.07 | 0.29% |
| extension | severe | 6 | 6 | - | 0.0 | $-1.26 | $-0.07 | 0.29% |
| combined | base | 15 | 13 | - | 1.4348880324034547 | $0.87 | $0.05 | 0.34% |
| combined | stress | 15 | 13 | 2/11 | 1.1738248365488289 | $0.35 | $0.02 | 0.33% |
| combined | severe | 15 | 13 | - | 0.946507007889381 | $-0.11 | $-0.01 | 0.33% |

## Combined stress slices

| Slice | Trades | PnL | $/month | DD |
|---|---:|---:|---:|---:|
| development | 2 | $0.30 | $0.06 | 0.05% |
| former_validation_now_diagnostic | 4 | $0.50 | $0.17 | 0.05% |
| retrospective | 7 | $-0.46 | $-0.06 | 0.25% |
| opened_design_month | 0 | $0.00 | $0.00 | 0.14% |

## Frozen gate

- Original-control regression: `{'stress_trades': 8, 'stress_net_pnl': 1.5964011161114513, 'severe_net_pnl': 1.142401644881943}`.
- Stress direction by universe: `{'original_control': {'LONG': {'trades': 2, 'wins': 1, 'net_pnl': 0.30099948938874377, 'mean_r': 0.6019989787774875}, 'SHORT': {'trades': 6, 'wins': 4, 'net_pnl': 1.2954016267227075, 'mean_r': 0.8636010844818051}}, 'extension': {'LONG': {'trades': 0, 'wins': 0, 'net_pnl': 0.0, 'mean_r': 0.0}, 'SHORT': {'trades': 6, 'wins': 1, 'net_pnl': -1.2405335373543949, 'mean_r': -0.8270223582362632}}, 'combined': {'LONG': {'trades': 2, 'wins': 1, 'net_pnl': 0.30099948938874377, 'mean_r': 0.6019989787774875}, 'SHORT': {'trades': 11, 'wins': 4, 'net_pnl': 0.046225099732623676, 'mean_r': 0.016809127175499518}}}`.
- Combined leave-one-symbol-out PnL: `{'BTCUSDT': 0.34722458912136744, 'ETHUSDT': -0.09632258694705342, 'SOLUSDT': -0.3025210908359668, 'BNBUSDT': 0.5972245891213674, 'XRPUSDT': -0.0759394698608844, 'DOGEUSDT': -0.18734692826524224, 'ADAUSDT': 0.34722458912136744, 'AVAXUSDT': 0.34722458912136744, 'LINKUSDT': 0.34722458912136744, 'LTCUSDT': 1.0972245891213674, 'BCHUSDT': 0.5972245891213674, 'DOTUSDT': 0.5964011161114513}`.
- Combined stress bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': -1.2014550239015591, 'p50_terminal_pnl': 0.3025642869171179, 'p90_terminal_pnl': 1.9457931655103329, 'observed_terminal_pnl': 0.34722458912136744}`.
- Combined monthly dispersion: `{'months': 17, 'positive_months': 4, 'positive_month_share': 0.23529411764705882, 'largest_positive_month_share_of_positive_pnl': 0.3447379033502435, 'best_month_pnl': 0.5504262327369247, 'worst_month_pnl': -0.75, 'monthly_pnl': {'2025-05-31 00:00:00+00:00': -0.24942674334818093, '2025-06-30 00:00:00+00:00': 0.0, '2025-07-31 00:00:00+00:00': 0.0, '2025-08-31 00:00:00+00:00': 0.0, '2025-09-30 00:00:00+00:00': 0.5504262327369247, '2025-10-31 00:00:00+00:00': 0.19354717606842087, '2025-11-30 00:00:00+00:00': 0.30946341664190413, '2025-12-31 00:00:00+00:00': 0.0, '2026-01-31 00:00:00+00:00': 0.0, '2026-02-28 00:00:00+00:00': -0.75, '2026-03-31 00:00:00+00:00': 0.0, '2026-04-30 00:00:00+00:00': -0.25, '2026-05-31 00:00:00+00:00': 0.0, '2026-06-30 00:00:00+00:00': 0.5432145070222987, '2026-07-31 00:00:00+00:00': 0.0, '2026-08-31 00:00:00+00:00': 0.0, '2026-09-30 00:00:00+00:00': 0.0}}`.
- Failed checks: `['extension_minimum_10_stress_fills', 'extension_stress_positive', 'extension_stress_pf_above_1_15', 'extension_severe_positive', 'extension_at_least_three_longs_and_shorts', 'extension_long_and_short_non_negative', 'extension_bootstrap_p10_positive', 'combined_minimum_18_stress_fills', 'combined_stress_improves_s108', 'combined_severe_improves_s108', 'combined_at_least_five_longs_and_shorts', 'three_of_four_positive_stress_slices', 'at_least_35pct_positive_months', 'combined_bootstrap_p10_positive']`.

**Decision: REJECTED_AT_HISTORICAL_GATE.**

A historical pass could only start a fresh paper-forward clock. It cannot authorize live trading or guarantee profit.
