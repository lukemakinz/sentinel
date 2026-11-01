# S100 — global direction + OI pullback swing

Protocol hash: `8b06a9a2704de0f8a1e6b38a69298358b07eaf090fde12c6f1554c831da64c39`.

**Discovery-contaminated historical characterization; not live approval.**

Layer 1 emits UP / DOWN / SIDEWAYS. Layer 2 trades EMA20 pullbacks with rising OI: long only in UP, short only in DOWN, cash in SIDEWAYS.

Target audit: `{'decisions': 254, 'invested_decisions': 59, 'long_decisions': 28, 'short_decisions': 31, 'cash_decisions': 195, 'sideways_decisions': 116}`.

## Global direction diagnostic

20-day BTC forward returns by regime: `{'UP': {'samples': 28, 'mean_forward_return_pct': 2.014763901516523, 'median_forward_return_pct': 0.41411849635321074, 'directional_hit_rate': 0.5357142857142857}, 'DOWN': {'samples': 30, 'mean_forward_return_pct': 1.9866565168796813, 'median_forward_return_pct': 1.542446578700607, 'directional_hit_rate': 0.43333333333333335}, 'SIDEWAYS': {'samples': 48, 'mean_forward_return_pct': -1.3074138968693458, 'median_forward_return_pct': -2.0820580215508033, 'directional_hit_rate': None}}`.

## Portfolio replay

| Period | Costs | PnL | Return | $/month | DD | Sharpe | Positive months |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | base | $-14.90 | -2.98% | $-1.66 | 6.58% | -0.62 | 11.1% |
| development | stress | $-15.80 | -3.16% | $-1.76 | 6.64% | -0.66 | 11.1% |
| development | severe | $-16.85 | -3.37% | $-1.88 | 6.72% | -0.71 | 11.1% |
| validation | base | $-4.97 | -1.02% | $-0.62 | 10.03% | -0.29 | 50.0% |
| validation | stress | $-5.98 | -1.23% | $-0.74 | 10.23% | -0.35 | 50.0% |
| validation | severe | $-7.15 | -1.48% | $-0.89 | 10.45% | -0.43 | 50.0% |
| retrospective_evaluation | base | $-23.04 | -4.80% | $-2.89 | 11.84% | -2.69 | 0.0% |
| retrospective_evaluation | stress | $-23.27 | -4.87% | $-2.91 | 12.16% | -2.72 | 0.0% |
| retrospective_evaluation | severe | $-23.53 | -4.94% | $-2.95 | 12.53% | -2.77 | 0.0% |

| Full replay | PnL | Return | DD | Sharpe | Daily-PnL PF | Funding |
|---|---:|---:|---:|---:|---:|---:|
| base | $-42.90 | -8.58% | 11.84% | -0.86 | 0.779 | $-1.93 |
| stress | $-45.04 | -9.01% | 12.16% | -0.90 | 0.770 | $-1.92 |
| severe | $-47.53 | -9.51% | 12.53% | -0.96 | 0.759 | $-1.92 |

## Direction and robustness

- Stress PnL by direction: `{'long_up_regime': -14.9259727284919, 'short_down_regime': -28.47308152909909, 'sideways_or_unclassified': -1.6441980476618028}`.
- OI threshold neighbors: `{'0.0': -53.221858957991856, '0.1': -38.54742602536464}`.
- Decision phase offsets: `{'1': -2.0102688435704863, '2': -14.415868714870328}`.
- Leave one traded symbol out: `{'BTCUSDT': -41.965202444311785, 'ETHUSDT': -35.66926601471869, 'SOLUSDT': -4.675637430040695}`.
- 28-day bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': -83.37973254767549, 'p50_terminal_pnl': -46.83435533807264, 'p90_terminal_pnl': -0.8790735055242732, 'observed_terminal_pnl': -45.04325230525279}`.

**Decision: REJECTED_AT_HISTORICAL_GATE.**

No parameter was changed after observing the replay. A historical pass would authorize paper-forward observation only.
