# S35 — post-funding exhaustion

Frozen protocol hash: `3014484bac55267184b73caa859688b0386f47146f0e7ba7b455e3de821d4569`.

| Window | Costs | Trades | WR | PF | Net | Avg/day | Median/day | Days >=$25 | DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development | base | 0 | 0.0% | None | $0.00 | $0.0000 | $0.0000 | 0.00% | 0.000% |
| development | stress | 0 | 0.0% | None | $0.00 | $0.0000 | $0.0000 | 0.00% | 0.000% |
| validation | base | 1 | 0.0% | 0.0 | $-0.47 | $-0.0013 | $0.0000 | 0.00% | 0.213% |
| validation | stress | 1 | 0.0% | 0.0 | $-0.50 | $-0.0014 | $0.0000 | 0.00% | 0.201% |
| retrospective_evaluation | base | 0 | 0.0% | None | $0.00 | $0.0000 | $0.0000 | 0.00% | 0.000% |
| retrospective_evaluation | stress | 0 | 0.0% | None | $0.00 | $0.0000 | $0.0000 | 0.00% | 0.000% |

Edge decision: **EDGE_FAIL**.
Income-target decision: **INCOME_TARGET_FAIL**.

The $25 target is evaluated over every calendar day, including days with no position. EDGE and INCOME_TARGET are deliberately separate. No failing result may be rescued by increasing leverage or risk.

## Candidate and loss audit

| Symbol | Final candidates | Executed trades | Stress net |
|---|---:|---:|---:|
| SUIUSDT | 0 | 0 | $0.00 |
| DOGEUSDT | 2 | 1 | $-0.50 |
| XRPUSDT | 0 | 0 | $0.00 |
| SOLUSDT | 0 | 0 | $0.00 |
| ETHUSDT | 0 | 0 | $0.00 |

The executed DOGE short entered at 2024-02-28 16:05 UTC and hit its 1R stop
15 minutes later. Before the stop, maximum favorable excursion was only
0.171R. Every diagnostic stop from 0.5R through 1.5R would have been hit before
even a 0.5R target. Over the full 180-minute observation path the market first
moved 17.709R against the short, and only later 1.639R in its favor. The
recorded loss was therefore caused by a false one-bar reversal confirmation,
not by the 2R target or a merely tight stop.

The second DOGE candidate was blocked because stress-inclusive sizing produced
only $19.21 notional, below the frozen conservative $20 minimum. A diagnostic
replay that ignores that execution block also hits the 1R stop (stress
-$0.4959); increasing size to force the order above $20 would breach the $0.50
risk cap.

These observations identify the mechanics of the two cases, but one executed
trade is not a statistical sample for choosing new parameters. Full
candle-by-candle and exit-grid evidence is in `AUDIT_SINGLE_TRADE.md`.

## Edge failure reasons

- development:trades<40
- development:net<=0
- development:PF<1.2
- validation:trades<25
- validation:net<=0
- validation:PF<1.1
- retrospective_evaluation:trades<25
- retrospective_evaluation:net<=0
- retrospective_evaluation:PF<1.1
- validation_evaluation:bootstrap_lower<=0
- direction_balance<20pct
- fewer_than_3_positive_symbols_with_5_trades
- DOGEUSDT:trade_share>40pct
- leave_out_SUIUSDT:net_or_PF_fail
- leave_out_DOGEUSDT:net_or_PF_fail
- leave_out_XRPUSDT:net_or_PF_fail
- leave_out_SOLUSDT:net_or_PF_fail
- leave_out_ETHUSDT:net_or_PF_fail

## Income-target failure reasons

- validation:mean_daily<25
- validation:bootstrap_lower<25
- retrospective_evaluation:mean_daily<25
- retrospective_evaluation:bootstrap_lower<25
