# FCM_SAFE25 — exact-hedge monthly funding carry

Frozen protocol hash: `ca4b236e2f33e69ccc0989ae53316f82ae254bff8f0478e16925a98c34f9ce2e`.

| Window | Cost case | Episodes | Funding | Basis PnL | Net | Return | Max DD | Min exit-ready futures equity | Max audited mark-high leverage | Emergency closes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development | base | 11 | $10.87 | $-0.13 | $9.87 | 3.949% | 0.433% | $135.20 | 0.664x | 0 |
| development | stress | 11 | $10.87 | $-0.13 | $9.18 | 3.674% | 0.433% | $135.15 | 0.664x | 0 |
| development | severe | 11 | $10.87 | $-0.13 | $8.25 | 3.298% | 0.446% | $135.08 | 0.664x | 0 |
| validation | base | 10 | $3.02 | $0.10 | $2.44 | 0.977% | 0.056% | $186.12 | 0.203x | 0 |
| validation | stress | 10 | $3.02 | $0.10 | $1.91 | 0.765% | 0.092% | $186.09 | 0.203x | 0 |
| validation | severe | 10 | $3.02 | $0.10 | $1.19 | 0.475% | 0.196% | $186.05 | 0.203x | 0 |
| retrospective_evaluation | base | 8 | $1.08 | $-0.02 | $0.54 | 0.218% | 0.077% | $186.62 | 0.198x | 0 |
| retrospective_evaluation | stress | 8 | $1.08 | $-0.02 | $0.14 | 0.054% | 0.137% | $186.59 | 0.198x | 0 |
| retrospective_evaluation | severe | 8 | $1.08 | $-0.02 | $-0.42 | -0.169% | 0.266% | $186.55 | 0.199x | 0 |
| all_available | base | 29 | $14.97 | $-0.04 | $12.86 | 5.142% | 0.433% | $135.20 | 0.664x | 0 |
| all_available | stress | 29 | $14.97 | $-0.04 | $11.23 | 4.491% | 0.433% | $135.15 | 0.664x | 0 |
| all_available | severe | 29 | $14.97 | $-0.04 | $9.01 | 3.604% | 0.446% | $135.08 | 0.664x | 0 |

## Frozen acceptance gates

| Gate | Result | Observed | Requirement |
|---|---:|---:|---:|
| stress_positive_development | PASS | 9.18394892 | > 0 USD |
| minimum_episodes_development | PASS | 11 | >= 6 |
| stress_positive_validation | PASS | 1.91150383 | > 0 USD |
| minimum_episodes_validation | PASS | 10 | >= 6 |
| stress_positive_retrospective_evaluation | PASS | 0.13557132 | > 0 USD |
| minimum_episodes_retrospective_evaluation | PASS | 8 | >= 6 |
| stress_positive_all_available | PASS | 11.22800823 | > 0 USD |
| minimum_episodes_all_available | PASS | 29 | >= 20 |
| no_emergency_close | PASS | 0 | == 0 |
| no_unfilled_emergency_close | PASS | 0 | == 0 |
| no_modelled_collateral_exhaustion | PASS | 0 | == 0 |
| exit_ready_futures_equity_buffer | PASS | 135.15069394 | >= 125 USD |
| high_mark_leverage_cap | PASS | 0.66387892 | <= 0.75x |
| mtm_drawdown_cap | PASS | 0.43327543 | <= 2% |
| pathwise_free_cash | PASS | 25.28215053 | >= 20 USD |
| ledger_reconciled | PASS | True | true |
| severe_positive_all_available | PASS | 9.00901457 | > 0 USD at 80 bps round trip |
| leave_BNBUSDT_out_positive | PASS | 13.39646395 | > 0 USD |
| leave_ETHUSDT_out_positive | PASS | 11.41505984 | > 0 USD |
| leave_SOLUSDT_out_positive | PASS | 9.06869223 | > 0 USD |
| top_symbol_concentration | PASS | 0.51260483 | <= 65% of gross profit |
| top_episode_concentration | PASS | 0.23183454 | <= 50% of gross profit |

## Leave-one-symbol-out stress

- without BNBUSDT: $13.3965 across 27 episodes
- without ETHUSDT: $11.4151 across 24 episodes
- without SOLUSDT: $9.0687 across 24 episodes

Decision: **HISTORICAL_GATE_PASS_PAPER_FORWARD_ONLY**.

## Interpretation boundary

- The newest stress window earned only $0.1356; at severe costs it earned $-0.4217.
- Emergency monitoring used checksum-verified real 1m mark highs. Any official 1m archive gap is covered by the containing official hourly mark high at hour close; execution is delayed until the next real open.
- Minute coverage was validated for 75 symbol-months and three separate streams.
- Current Binance common lot steps were applied to both legs: ETH 0.001, SOL 0.01 and BNB 0.01. Rounding down left $36.31 undeployed across all 29 entries.
- Every historical period was already inspected in predecessor research. A pass permits paper-forward observation only; it is not evidence that future profit is guaranteed.
