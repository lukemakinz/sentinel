# S111 — S108 with close-confirmed 1R cost breakeven

Protocol hash: `ffebc088c600ff172f40869b3d1c214239ecc4876a3349c29fe462a1ac936ec6`.

**Post-S110, selection-contaminated diagnostic. Live remains disabled.**

Entries, initial stops, targets and sizing are unchanged. The candidate moves the stop to a cost-covering breakeven only after a completed 15m close reaches +1R; the update applies to the next 5m candle.

| Policy | Costs | Trades | Long/short | WR | PF | PnL | $/month | DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| initial_sl_only | base | 8 | - | 62.5% | 3.8303377121058007 | $2.12 | $0.12 | 0.191% |
| initial_sl_only | stress | 8 | 2/6 | 62.5% | 3.1331481102869208 | $1.60 | $0.09 | 0.183% |
| initial_sl_only | severe | 8 | - | 62.5% | 2.5261677120721338 | $1.14 | $0.07 | 0.176% |
| delayed_cost_be_1r | base | 8 | - | 50.0% | 4.461931148555625 | $1.73 | $0.10 | 0.141% |
| delayed_cost_be_1r | stress | 8 | 2/6 | 50.0% | 3.591637547082062 | $1.29 | $0.08 | 0.134% |
| delayed_cost_be_1r | severe | 8 | - | 50.0% | 2.835754837162993 | $0.92 | $0.05 | 0.126% |

## Candidate diagnostics

- Raw signals: `9`; setup IDs: `['BNBUSDT:2026-02-02T16:15:00+00:00:SHORT', 'DOGEUSDT:2026-06-11T19:45:00+00:00:SHORT', 'DOGEUSDT:2026-06-20T07:30:00+00:00:SHORT', 'ETHUSDT:2025-10-23T08:30:00+00:00:SHORT', 'ETHUSDT:2025-11-08T04:45:00+00:00:SHORT', 'SOLUSDT:2025-05-25T02:30:00+00:00:LONG', 'SOLUSDT:2025-09-15T17:30:00+00:00:LONG', 'SOLUSDT:2025-11-08T03:15:00+00:00:SHORT', 'XRPUSDT:2026-06-12T09:45:00+00:00:SHORT']`.
- Stress directions: `{'LONG': {'trades': 2, 'wins': 0, 'net_pnl': -0.25064060369066965, 'mean_r': -0.5012812073813393}, 'SHORT': {'trades': 6, 'wins': 4, 'net_pnl': 1.5454016267227075, 'mean_r': 1.0302677511484717}}`.
- Stress slices: `{'development': -0.25064060369066965, 'former_validation_now_diagnostic': 1.0021871197004089, 'retrospective': 0.5432145070222987, 'opened_design_month': 0.0}`.
- Stress bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': 0.11749451816921237, 'p50_terminal_pnl': 1.2051665770812008, 'p90_terminal_pnl': 2.5680567198464814, 'observed_terminal_pnl': 1.2947610230320379}`.
- Stress stop updates: `{'trades_with_updates': 6, 'updates': 6, 'minimum_closed_bar_r': 1.0725399966985998, 'reasons': ['COST_BE']}`.
- Failed checks: `['minimum_18_stress_fills', 'at_least_five_longs_and_shorts', 'stress_improves_by_at_least_0_25usd', 'severe_improves_by_at_least_0_25usd', 'both_directions_non_negative', 'three_of_four_positive_stress_slices', 'bootstrap_p10_improves']`.

**Decision: REJECTED_AT_HISTORICAL_GATE.**

Historical improvement is not a profit guarantee and cannot authorize live trading.
