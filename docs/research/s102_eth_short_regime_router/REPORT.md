# S102 — ETH-only short regime router

Protocol hash: `e97a9e5b495f52097215414c55ba0e0fd67c407f61f2ba026213e1e2e8e23094`.

**Selected after S101 ablation: positive history can authorize paper-forward only.**

Target audit: `{'decisions': 109, 'invested_decisions': 48, 'long_decisions': 29, 'short_decisions': 19, 'cash_decisions': 61, 'sideways_decisions': 41}`.
Global regime diagnostic: `{'UP': {'samples': 33, 'mean_forward_return_pct': 1.109203318903956, 'median_forward_return_pct': -0.23857876984476611, 'directional_hit_rate': 0.45454545454545453}, 'DOWN': {'samples': 33, 'mean_forward_return_pct': -0.46716912029351854, 'median_forward_return_pct': -1.8316440739355233, 'directional_hit_rate': 0.5454545454545454}, 'SIDEWAYS': {'samples': 40, 'mean_forward_return_pct': 0.8017522286245009, 'median_forward_return_pct': 1.5977843041941941, 'directional_hit_rate': None}}`.

| Period | Costs | PnL | Return | $/month | DD | Sharpe | Positive months |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | base | $65.82 | 13.16% | $7.34 | 7.99% | 1.56 | 44.4% |
| development | stress | $64.48 | 12.90% | $7.19 | 8.04% | 1.53 | 44.4% |
| development | severe | $62.91 | 12.58% | $7.01 | 8.09% | 1.50 | 44.4% |
| validation | base | $37.92 | 6.70% | $4.71 | 8.20% | 0.93 | 62.5% |
| validation | stress | $36.34 | 6.44% | $4.51 | 8.34% | 0.90 | 62.5% |
| validation | severe | $34.51 | 6.13% | $4.29 | 8.51% | 0.86 | 62.5% |
| retrospective_evaluation | base | $-0.37 | -0.06% | $-0.05 | 3.69% | -0.00 | 25.0% |
| retrospective_evaluation | stress | $-0.83 | -0.14% | $-0.10 | 3.73% | -0.03 | 25.0% |
| retrospective_evaluation | severe | $-1.35 | -0.23% | $-0.17 | 3.78% | -0.07 | 25.0% |

| Full replay | PnL | Return | DD | Sharpe | Daily-PnL PF | Funding |
|---|---:|---:|---:|---:|---:|---:|
| base | $103.37 | 20.67% | 8.20% | 1.01 | 1.239 | $-5.00 |
| stress | $99.99 | 20.00% | 8.34% | 0.98 | 1.231 | $-4.99 |
| severe | $96.07 | 19.21% | 8.51% | 0.95 | 1.222 | $-4.98 |

- Stress average: **$4.00/month** on the selected $500 history.
- Stress PnL by direction: `{'long_up_regime': 97.2759979570099, 'short_down_regime': 3.8540240815572133, 'sideways_or_unclassified': -1.1421199954045846}`.
- Risk neighbors: `{'0.125_0.0625': 82.8669985349186, '0.175_0.0875': 117.27103459811804}`.
- OI threshold neighbors: `{'0.0': 99.98790204316253, '0.1': 99.98790204316253}`.
- Weekly phase offsets: `{'2': 88.79560690354378, '4': 126.21079349042373}`.
- Bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': -2.520599191676415, 'p50_terminal_pnl': 90.17481873532, 'p90_terminal_pnl': 240.3803467655047, 'observed_terminal_pnl': 99.98790204316253}`.

**Decision: HISTORICAL_POSITIVE_SELECTED_PAPER_CHALLENGER.**

Live remains disabled. The prospective clock starts on 2026-10-19.
