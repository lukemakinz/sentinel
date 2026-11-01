# S109 — session liquidity atlas

Protocol hash: `8a54998c1e75db1fb2856cf29b41a3953dce99bb60bf547e2758bf2feaf849dd`.

**Post-S108, selection-contaminated diagnostic. Live remains disabled.**

S109 retains S108 flow, funding, stop, target and risk rules. It replaces the single rolling level with prior-day, prior-week and completed 00:00–08:00 UTC Asia-session anchors, then waits up to 90 minutes for the same failed-auction confirmation.

| Universe | Costs | Signals | Trades | WR | PF | PnL | $/month | DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| combined | base | 15 | 13 | 46.2% | 1.8096290669453714 | $1.42 | $0.08 | 0.19% |
| combined | stress | 15 | 13 | 46.2% | 1.4141781461813274 | $0.73 | $0.04 | 0.19% |
| combined | severe | 15 | 12 | 50.0% | 1.2690852441939322 | $0.40 | $0.02 | 0.19% |
| primary | base | 7 | 6 | 33.3% | 1.212448444083327 | $0.21 | $0.01 | 0.19% |
| primary | stress | 7 | 6 | 33.3% | 1.034380157116535 | $0.03 | $0.00 | 0.19% |
| primary | severe | 7 | 6 | 33.3% | 0.8696184699626132 | $-0.13 | $-0.01 | 0.19% |
| portability | base | 8 | 7 | 57.1% | 2.603888673120206 | $1.21 | $0.07 | 0.15% |
| portability | stress | 8 | 7 | 57.1% | 1.9194433352132727 | $0.69 | $0.04 | 0.14% |
| portability | severe | 8 | 6 | 66.7% | 2.06544414928762 | $0.53 | $0.03 | 0.13% |

## Combined stress slices

| Slice | Trades | PnL | $/month | DD | Sharpe |
|---|---:|---:|---:|---:|---:|
| development | 1 | $-0.25 | $-0.05 | 0.05% | -1.54 |
| former_validation_now_diagnostic | 6 | $1.18 | $0.39 | 0.15% | 2.52 |
| retrospective | 6 | $-0.21 | $-0.03 | 0.15% | -0.32 |
| opened_design_month | 0 | $0.00 | $0.00 | 0.04% | 0.00 |

## Attribution and frozen gate

- Combined stress direction: `{'LONG': {'trades': 1, 'wins': 0, 'net_pnl': -0.25004986582740685, 'mean_r': -1.0001994633096276}, 'SHORT': {'trades': 12, 'wins': 6, 'net_pnl': 0.9759243464496876, 'mean_r': 0.3253081154832292}}`.
- Combined stress per symbol: `{'BTCUSDT': {'trades': 3, 'net_pnl': -0.02373697157361221, 'gross_profit': 0.4762630284263878}, 'ETHUSDT': {'trades': 1, 'net_pnl': -0.25045557207977254, 'gross_profit': 0.0}, 'SOLUSDT': {'trades': 2, 'net_pnl': 0.30859007780458114, 'gross_profit': 0.558639943631988}, 'BNBUSDT': {'trades': 2, 'net_pnl': 0.22403080102185413, 'gross_profit': 0.47403080102185413}, 'XRPUSDT': {'trades': 3, 'net_pnl': 0.3467394300303681, 'gross_profit': 0.5990740119157181}, 'DOGEUSDT': {'trades': 2, 'net_pnl': 0.12070671541886213, 'gross_profit': 0.37043255965068056}}`.
- Leave-one-out: `{'BTCUSDT': 0.749611452195893, 'ETHUSDT': 0.9763300527020533, 'SOLUSDT': 0.6271781558810972, 'BNBUSDT': 0.5018436796004266, 'XRPUSDT': 0.37913505059191266, 'DOGEUSDT': 1.0283318241856705}`.
- Monthly dispersion: `{'months': 17, 'positive_months': 3, 'positive_month_share': 0.17647058823529413, 'largest_positive_month_share_of_positive_pnl': 0.5383043035425145, 'best_month_pnl': 0.9290725032826685, 'worst_month_pnl': -0.5, 'monthly_pnl': {'2025-05-31 00:00:00+00:00': 0.0, '2025-06-30 00:00:00+00:00': 0.0, '2025-07-31 00:00:00+00:00': 0.0, '2025-08-31 00:00:00+00:00': -0.25004986582740685, '2025-09-30 00:00:00+00:00': 0.0, '2025-10-31 00:00:00+00:00': -0.5, '2025-11-30 00:00:00+00:00': 0.9290725032826685, '2025-12-31 00:00:00+00:00': 0.7533254091572985, '2026-01-31 00:00:00+00:00': 0.0, '2026-02-28 00:00:00+00:00': 0.0, '2026-03-31 00:00:00+00:00': 0.0, '2026-04-30 00:00:00+00:00': -0.25, '2026-05-31 00:00:00+00:00': 0.0, '2026-06-30 00:00:00+00:00': 0.04352643400972056, '2026-07-31 00:00:00+00:00': 0.0, '2026-08-31 00:00:00+00:00': 0.0, '2026-09-30 00:00:00+00:00': 0.0}}`.
- Bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': -0.7819480080876302, 'p50_terminal_pnl': 0.6826501546592851, 'p90_terminal_pnl': 2.310219619783192, 'observed_terminal_pnl': 0.7258744806222808}`.
- S108 reference: stress `$1.5964`, severe `$1.1424`.
- Failed checks: `['combined_minimum_18_stress_fills', 'stress_pnl_beats_s108', 'severe_pnl_beats_s108', 'at_least_five_longs_and_shorts', 'long_and_short_non_negative', 'primary_and_portability_severe_non_negative', 'three_of_four_positive_stress_slices', 'positive_month_share_at_least_35pct', 'bootstrap_p10_positive']`.

**Decision: REJECTED_AT_HISTORICAL_GATE.**

No historical pass can authorize live trading or guarantee profit.
