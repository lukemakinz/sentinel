# S105 — liquidity auction ablation

Frozen protocol: `334965e1c62494a1a32d6a62269ac8fea0243985159cbfe2eb751f9a174bb6cc`.

**Post-S104, selection-contaminated research. Live remains disabled.**

| Variant | Costs | Trades | WR | PF | PnL | $/month | DD |
|---|---|---:|---:|---:|---:|---:|---:|
| geometry | base | 15 | 40.0% | 1.7505617701042597 | $2.27 | $0.14 | 0.33% |
| geometry | stress | 15 | 40.0% | 1.5490746891016673 | $1.72 | $0.11 | 0.33% |
| geometry | severe | 14 | 42.9% | 1.6313396304202554 | $1.72 | $0.11 | 0.33% |
| geometry_reset | base | 7 | 42.9% | 1.4423156175434382 | $0.55 | $0.03 | 0.29% |
| geometry_reset | stress | 7 | 42.9% | 1.1779169732065813 | $0.23 | $0.01 | 0.29% |
| geometry_reset | severe | 7 | 42.9% | 0.8247593669578963 | $-0.23 | $-0.01 | 0.28% |
| geometry_target | base | 0 | 0.0% | None | $0.00 | $0.00 | 0.00% |
| geometry_target | stress | 0 | 0.0% | None | $0.00 | $0.00 | 0.00% |
| geometry_target | severe | 0 | 0.0% | None | $0.00 | $0.00 | 0.00% |
| full | base | 0 | 0.0% | None | $0.00 | $0.00 | 0.00% |
| full | stress | 0 | 0.0% | None | $0.00 | $0.00 | 0.00% |
| full | severe | 0 | 0.0% | None | $0.00 | $0.00 | 0.00% |

## Stress slices

| Variant | Development | Validation | Retrospective |
|---|---:|---:|---:|
| geometry | $0.27 | $2.27 | $-0.83 |
| geometry_reset | $0.71 | $0.00 | $-0.48 |
| geometry_target | $0.00 | $0.00 | $0.00 |
| full | $0.00 | $0.00 | $0.00 |

## Frozen diagnostics

### geometry

- Signals: `{'BTCUSDT': 6, 'ETHUSDT': 6, 'SOLUSDT': 3}`.
- Stress attribution: `{'DEFENSE': {'trades': 15, 'net_pnl': 1.7167817850047982, 'wins': 6}, 'IFVG': {'trades': 0, 'net_pnl': 0.0, 'wins': 0}, 'LONG': {'trades': 8, 'net_pnl': -0.143640818793358, 'wins': 3}, 'SHORT': {'trades': 7, 'net_pnl': 1.8604226037981562, 'wins': 3}}`.
- Leave-one-out: `{'BTCUSDT': 4.068016791729235, 'ETHUSDT': -0.9705163901201104, 'SOLUSDT': 0.33606316840047157}`.
- Bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': -1.7924163997575193, 'p50_terminal_pnl': 1.420547464207658, 'p90_terminal_pnl': 5.727924077991106, 'observed_terminal_pnl': 1.7167817850047982}`.
- Decision: **REJECTED_AT_HISTORICAL_GATE**.

### geometry_reset

- Signals: `{'BTCUSDT': 1, 'ETHUSDT': 4, 'SOLUSDT': 2}`.
- Stress attribution: `{'DEFENSE': {'trades': 7, 'net_pnl': 0.22670603653324406, 'wins': 3}, 'IFVG': {'trades': 0, 'net_pnl': 0.0, 'wins': 0}, 'LONG': {'trades': 3, 'net_pnl': 0.5802687967598104, 'wins': 2}, 'SHORT': {'trades': 4, 'net_pnl': -0.3535627602265663, 'wins': 1}}`.
- Leave-one-out: `{'BTCUSDT': 0.725483109468712, 'ETHUSDT': -0.13667478357717755, 'SOLUSDT': -0.1353962528250463}`.
- Bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': -1.0363197117454832, 'p50_terminal_pnl': 0.22467519645550738, 'p90_terminal_pnl': 1.593865104444717, 'observed_terminal_pnl': 0.22670603653324406}`.
- Decision: **REJECTED_AT_HISTORICAL_GATE**.

### geometry_target

- Signals: `{'BTCUSDT': 0, 'ETHUSDT': 0, 'SOLUSDT': 0}`.
- Stress attribution: `{'DEFENSE': {'trades': 0, 'net_pnl': 0.0, 'wins': 0}, 'IFVG': {'trades': 0, 'net_pnl': 0.0, 'wins': 0}, 'LONG': {'trades': 0, 'net_pnl': 0.0, 'wins': 0}, 'SHORT': {'trades': 0, 'net_pnl': 0.0, 'wins': 0}}`.
- Leave-one-out: `{'BTCUSDT': 0.0, 'ETHUSDT': 0.0, 'SOLUSDT': 0.0}`.
- Bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': 0.0, 'p50_terminal_pnl': 0.0, 'p90_terminal_pnl': 0.0, 'observed_terminal_pnl': 0.0}`.
- Decision: **REJECTED_AT_HISTORICAL_GATE**.

### full

- Signals: `{'BTCUSDT': 0, 'ETHUSDT': 0, 'SOLUSDT': 0}`.
- Stress attribution: `{'DEFENSE': {'trades': 0, 'net_pnl': 0.0, 'wins': 0}, 'IFVG': {'trades': 0, 'net_pnl': 0.0, 'wins': 0}, 'LONG': {'trades': 0, 'net_pnl': 0.0, 'wins': 0}, 'SHORT': {'trades': 0, 'net_pnl': 0.0, 'wins': 0}}`.
- Leave-one-out: `{'BTCUSDT': 0.0, 'ETHUSDT': 0.0, 'SOLUSDT': 0.0}`.
- Bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': 0.0, 'p50_terminal_pnl': 0.0, 'p90_terminal_pnl': 0.0, 'observed_terminal_pnl': 0.0}`.
- Decision: **REJECTED_AT_HISTORICAL_GATE**.

- Geometry stop neighbors: `{'1.75': {'signals': 16, 'trades': 16, 'net_pnl': 1.2167817850047982, 'profit_factor': 1.335508292161674, 'max_drawdown_pct': 0.4036247516204017}, '2.25': {'signals': 12, 'trades': 12, 'net_pnl': 0.7717922273449176, 'profit_factor': 1.2937432330195806, 'max_drawdown_pct': 0.40174516632567325}}`.
- Geometry age neighbors: `{'12': {'signals': 12, 'trades': 12, 'net_pnl': 0.5473268727444633, 'profit_factor': 1.1781593169491051, 'max_drawdown_pct': 0.3056453380029245}, '36': {'signals': 15, 'trades': 15, 'net_pnl': 1.7167817850047982, 'profit_factor': 1.5490746891016673, 'max_drawdown_pct': 0.33077526716867034}}`.

**Overall decision: ALL_VARIANTS_REJECTED_AT_HISTORICAL_GATE.**

No historical pass is live approval; it can only start a new prospective paper clock.
