# S101 — asymmetric global regime + trend/OI execution

Protocol hash: `f6c6717dccfb9a26257cea0aff57bea6dc56d5ad9632dc51be93dd31f1f906e7`.

**Post-S100, discovery-contaminated diagnostic; not live approval.**

Target audit: `{'decisions': 109, 'invested_decisions': 53, 'long_decisions': 29, 'short_decisions': 24, 'cash_decisions': 56, 'sideways_decisions': 41}`.
Regime occupancy: `{'SIDEWAYS': 0.4178712220762155, 'UP': 0.2996057818659658, 'DOWN': 0.28252299605781866}`.
20-day BTC diagnostic: `{'UP': {'samples': 33, 'mean_forward_return_pct': 1.109203318903956, 'median_forward_return_pct': -0.23857876984476611, 'directional_hit_rate': 0.45454545454545453}, 'DOWN': {'samples': 33, 'mean_forward_return_pct': -0.46716912029351854, 'median_forward_return_pct': -1.8316440739355233, 'directional_hit_rate': 0.5454545454545454}, 'SIDEWAYS': {'samples': 40, 'mean_forward_return_pct': 0.8017522286245009, 'median_forward_return_pct': 1.5977843041941941, 'directional_hit_rate': None}}`.

| Period | Costs | PnL | Return | $/month | DD | Sharpe | Positive months |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | base | $57.35 | 11.47% | $6.39 | 9.62% | 1.33 | 66.7% |
| development | stress | $55.90 | 11.18% | $6.23 | 9.67% | 1.30 | 66.7% |
| development | severe | $54.21 | 10.84% | $6.04 | 9.72% | 1.26 | 66.7% |
| validation | base | $39.54 | 7.09% | $4.91 | 10.17% | 0.98 | 62.5% |
| validation | stress | $37.89 | 6.82% | $4.71 | 10.31% | 0.95 | 62.5% |
| validation | severe | $35.97 | 6.49% | $4.47 | 10.48% | 0.90 | 62.5% |
| retrospective_evaluation | base | $-16.31 | -2.73% | $-2.04 | 5.38% | -0.74 | 37.5% |
| retrospective_evaluation | stress | $-17.21 | -2.90% | $-2.16 | 5.55% | -0.79 | 37.5% |
| retrospective_evaluation | severe | $-18.24 | -3.09% | $-2.29 | 5.78% | -0.85 | 37.5% |

| Full replay | PnL | Return | DD | Sharpe | Daily-PnL PF | Funding |
|---|---:|---:|---:|---:|---:|---:|
| base | $80.58 | 16.12% | 10.17% | 0.78 | 1.167 | $-5.00 |
| stress | $76.58 | 15.32% | 10.31% | 0.75 | 1.158 | $-4.99 |
| severe | $71.94 | 14.39% | 10.48% | 0.71 | 1.148 | $-4.97 |

- Stress PnL by direction: `{'long_up_regime': 97.12311504268041, 'short_down_regime': -18.999358360936526, 'sideways_or_unclassified': -1.5466107880490654}`.
- Volatility-risk neighbors: `{'0.125_0.0625': 63.891877160696936, '0.175_0.0875': 89.20579145244187}`.
- Weekly phase offsets: `{'2': 85.34219100813402, '4': 83.41951723968134}`.
- Leave-one-traded-asset-out: `{'BTCUSDT': 94.04880657392653, 'ETHUSDT': 69.49645177576258, 'SOLUSDT': 62.92526136267293, 'BNBUSDT': 59.60074109476466, 'XRPUSDT': 69.08401729530135, 'DOGEUSDT': 32.160845060641236}`.
- Bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': -28.314508838674577, 'p50_terminal_pnl': 68.31683121729242, 'p90_terminal_pnl': 216.1006075344831, 'observed_terminal_pnl': 76.57714589369482}`.

**Decision: REJECTED_AT_HISTORICAL_GATE.**

No S101 parameter was changed after its protocol was hashed.
