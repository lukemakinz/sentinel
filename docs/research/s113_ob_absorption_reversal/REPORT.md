# S113 — OB Absorption Reversal

Protocol hash: `2d2073f50c65dd6a11864be2dd3d5b2f33e9bb1fc3c618ebe4b2edd3ddf1e9ad`.

Capital $250, risk 0.2% per trade, up to 2 positions, 12 symbols; 1m execution
with fees, slippage and funding. Target for comparison: $5/day.

| Route | Window | Costs | Fills | WR | PF | Mean R | PnL | $/day | Gap to $5/day | Max DD |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | in_sample_reference | base | 86 | 22.1% | 0.99 | -0.001 | $-0.25 | $-0.002 | $5.00 | 3.33% |
| CONTROL | in_sample_reference | stress | 85 | 21.2% | 0.77 | -0.126 | $-7.16 | $-0.047 | $5.05 | 4.31% |
| CONTROL | in_sample_reference | severe | 80 | 23.8% | 0.82 | -0.135 | $-5.44 | $-0.036 | $5.04 | 3.98% |
| CONTROL | held_out | base | 192 | 24.5% | 1.06 | 0.058 | $4.26 | $0.013 | $4.99 | 4.88% |
| CONTROL | held_out | stress | 183 | 24.6% | 0.97 | -0.008 | $-1.88 | $-0.006 | $5.01 | 4.93% |
| CONTROL | held_out | severe | 173 | 22.5% | 0.80 | -0.171 | $-10.97 | $-0.033 | $5.03 | 5.55% |
| CONTROL | validation | base | 103 | 29.1% | 1.28 | 0.204 | $10.50 | $0.058 | $4.94 | 2.56% |
| CONTROL | validation | stress | 99 | 29.3% | 1.21 | 0.147 | $7.24 | $0.040 | $4.96 | 2.45% |
| CONTROL | validation | severe | 95 | 27.4% | 0.98 | -0.008 | $-0.52 | $-0.003 | $5.00 | 2.55% |
| CONTROL | evaluation | base | 89 | 19.1% | 0.81 | -0.111 | $-5.99 | $-0.039 | $5.04 | 4.88% |
| CONTROL | evaluation | stress | 84 | 19.0% | 0.72 | -0.192 | $-8.37 | $-0.055 | $5.05 | 4.53% |
| CONTROL | evaluation | severe | 78 | 16.7% | 0.53 | -0.368 | $-12.42 | $-0.081 | $5.08 | 5.11% |
| ABSORB | in_sample_reference | base | 33 | 24.2% | 1.05 | 0.014 | $0.60 | $0.004 | $5.00 | 2.06% |
| ABSORB | in_sample_reference | stress | 33 | 24.2% | 0.93 | -0.056 | $-0.87 | $-0.006 | $5.01 | 2.14% |
| ABSORB | in_sample_reference | severe | 31 | 25.8% | 0.89 | -0.077 | $-1.23 | $-0.008 | $5.01 | 1.97% |
| ABSORB | held_out | base | 46 | 26.1% | 1.19 | 0.140 | $3.28 | $0.010 | $4.99 | 2.16% |
| ABSORB | held_out | stress | 44 | 25.0% | 1.00 | 0.005 | $0.02 | $0.000 | $5.00 | 2.41% |
| ABSORB | held_out | severe | 43 | 23.3% | 0.80 | -0.148 | $-3.23 | $-0.010 | $5.01 | 2.81% |
| ABSORB | validation | base | 23 | 26.1% | 1.10 | 0.070 | $0.81 | $0.004 | $5.00 | 1.00% |
| ABSORB | validation | stress | 23 | 26.1% | 0.98 | -0.009 | $-0.14 | $-0.001 | $5.00 | 1.00% |
| ABSORB | validation | severe | 22 | 22.7% | 0.72 | -0.213 | $-2.36 | $-0.013 | $5.01 | 1.52% |
| ABSORB | evaluation | base | 23 | 26.1% | 1.29 | 0.209 | $2.47 | $0.016 | $4.98 | 2.16% |
| ABSORB | evaluation | stress | 21 | 23.8% | 1.02 | 0.020 | $0.16 | $0.001 | $5.00 | 2.06% |
| ABSORB | evaluation | severe | 21 | 23.8% | 0.89 | -0.080 | $-0.88 | $-0.006 | $5.01 | 1.99% |
| ABSORB_PARTIAL | in_sample_reference | base | 33 | 36.4% | 1.02 | -0.001 | $0.22 | $0.001 | $5.00 | 1.56% |
| ABSORB_PARTIAL | in_sample_reference | stress | 33 | 33.3% | 0.88 | -0.076 | $-1.21 | $-0.008 | $5.01 | 1.74% |
| ABSORB_PARTIAL | in_sample_reference | severe | 31 | 35.5% | 0.81 | -0.121 | $-1.90 | $-0.012 | $5.01 | 1.81% |
| ABSORB_PARTIAL | held_out | base | 46 | 39.1% | 1.18 | 0.101 | $2.43 | $0.007 | $4.99 | 1.83% |
| ABSORB_PARTIAL | held_out | stress | 44 | 34.1% | 0.92 | -0.046 | $-1.06 | $-0.003 | $5.00 | 2.35% |
| ABSORB_PARTIAL | held_out | severe | 43 | 30.2% | 0.72 | -0.181 | $-3.90 | $-0.012 | $5.01 | 3.07% |
| ABSORB_PARTIAL | validation | base | 23 | 30.4% | 0.94 | -0.044 | $-0.50 | $-0.003 | $5.00 | 1.00% |
| ABSORB_PARTIAL | validation | stress | 23 | 30.4% | 0.83 | -0.114 | $-1.34 | $-0.007 | $5.01 | 1.00% |
| ABSORB_PARTIAL | validation | severe | 22 | 27.3% | 0.62 | -0.278 | $-3.06 | $-0.017 | $5.02 | 1.42% |
| ABSORB_PARTIAL | evaluation | base | 23 | 47.8% | 1.50 | 0.246 | $2.93 | $0.019 | $4.98 | 1.83% |
| ABSORB_PARTIAL | evaluation | stress | 21 | 38.1% | 1.05 | 0.029 | $0.28 | $0.002 | $5.00 | 1.85% |
| ABSORB_PARTIAL | evaluation | severe | 21 | 33.3% | 0.86 | -0.079 | $-0.85 | $-0.006 | $5.01 | 1.94% |

- **CONTROL: CONTROL_NOT_PROMOTABLE**
- **ABSORB: REJECTED_AT_HELD_OUT_GATE** — failed checks: ['fills', 'profit_factor', 'mean_net_r', 'severe_pnl_positive', 'subwindows_pf']
- **ABSORB_PARTIAL: REJECTED_AT_HELD_OUT_GATE** — failed checks: ['fills', 'profit_factor', 'mean_net_r', 'stress_pnl_positive', 'severe_pnl_positive', 'subwindows_pf', 'beats_control']

Retrospective research only; no live approval.
