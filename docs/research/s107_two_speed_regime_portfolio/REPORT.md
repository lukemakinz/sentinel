# S107 — two-speed regime portfolio

Protocol hash: `150d83fec934ce3b6494e9003ef741575ba42154f4b0ff12800e159ff833f2f8`.

**Historical portfolio-construction diagnostic; all shared history is selection-contaminated. Live remains disabled.**

Control is $250 Book A + $250 cash. The two candidates replace only the cash reserve with the frozen S102 sleeve or its mechanical ETH-short-only filter.

| Costs | Variant | PnL | $/month | DD | ES95 daily | PF |
|---|---|---:|---:|---:|---:|---:|
| base | book_a_cash | $123.44 | $7.70 | 4.01% | -0.945% | 1.685 |
| base | book_a_s102_full | $140.03 | $8.73 | 4.75% | -1.024% | 1.588 |
| base | book_a_s102_short_only | $123.17 | $7.68 | 4.01% | -0.945% | 1.581 |
| stress | book_a_cash | $122.15 | $7.62 | 4.01% | -0.945% | 1.677 |
| stress | book_a_s102_full | $137.87 | $8.60 | 4.76% | -1.026% | 1.578 |
| stress | book_a_s102_short_only | $121.69 | $7.59 | 4.01% | -0.945% | 1.573 |
| severe | book_a_cash | $122.21 | $7.62 | 4.02% | -0.935% | 1.682 |
| severe | book_a_s102_full | $136.94 | $8.54 | 4.78% | -1.017% | 1.576 |
| severe | book_a_s102_short_only | $121.54 | $7.58 | 4.02% | -0.935% | 1.575 |

## Stress-cost time slices

| Slice | Control | Full S102 | Short-only | Full excess | Short excess |
|---|---:|---:|---:|---:|---:|
| development | $90.96 | $105.42 | $90.96 | $14.46 | $0.00 |
| former_validation_now_diagnostic | $35.46 | $35.74 | $33.65 | $0.28 | $-1.81 |
| former_evaluation_now_diagnostic | $-4.28 | $-3.29 | $-2.93 | $0.99 | $1.35 |

## Frozen gate

- `book_a_s102_full`: **FAIL**; failed checks: `['stress_positive_excess_month_share_at_least_50pct', 'paired_bootstrap_lower_above_zero', 'short_contribution_positive']`.
- `book_a_s102_short_only`: **FAIL**; failed checks: `['beats_control_base_stress_severe', 'stress_positive_excess_month_share_at_least_50pct', 'paired_bootstrap_lower_above_zero', 'short_contribution_positive']`.

S102 target audit in the shared window: `{'full': {'decisions': 70, 'invested_decisions': 30, 'long_decisions': 17, 'short_decisions': 13, 'cash_decisions': 40, 'sideways_decisions': 30}, 'short_only': {'decisions': 70, 'invested_decisions': 13, 'long_decisions': 0, 'short_decisions': 13, 'cash_decisions': 57, 'sideways_decisions': 30}}`.
Stress S102 direction PnL: `{'long_up_regime': 16.471844114463977, 'short_down_regime': -0.3725475687440962, 'sideways_or_unclassified': -0.37178806962378985}`.
Stress short-only evidence: `{'net_pnl': -0.4538638344924948, 'funding_pnl': 0.21538089439487584, 'rebalances': 70}`.
Stress sleeve correlations: `{'book_a_vs_s102_full': 0.029432620386394603, 'book_a_vs_s102_short_only': 0.00022008753422473102}`.

**Decision: BOTH_CANDIDATES_REJECTED_AT_HISTORICAL_GATE.**

A historical pass would authorize a fresh paper-forward challenger only. It would not prove profitability and would not enable live trading.
