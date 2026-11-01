# S104 — liquidity-sweep-anchored FVG/IFVG

Frozen protocol: `922478096156e9ecdded970cffc629f57839a50e96899cdaab40762fcdf744ee`.

**Only the sweep qualification and stop anchor changed from S103.**
All history is contaminated; live remains disabled.

| Replay | Trades | WR | PF | PnL | $/month | DD |
|---|---:|---:|---:|---:|---:|---:|
| S104 base | 28 | 28.6% | 0.7436651388068859 | $-2.19 | $-0.14 | 0.78% |
| S104 stress | 28 | 28.6% | 0.6581769260606039 | $-2.95 | $-0.18 | 0.80% |
| S104 severe | 27 | 29.6% | 0.624088344140332 | $-3.09 | $-0.19 | 0.82% |
| S103 stress reference | 104 | 26.0% | 0.5468002004575767 | $-15.79 | $-0.99 | 3.77% |

| Period | Costs | Trades | PnL | $/month | DD | Sharpe |
|---|---|---:|---:|---:|---:|---:|
| development | base | 8 | $-0.53 | $-0.11 | 0.20% | -0.51 |
| development | stress | 8 | $-0.73 | $-0.15 | 0.20% | -0.72 |
| development | severe | 7 | $-0.42 | $-0.08 | 0.20% | -0.44 |
| validation | base | 11 | $0.96 | $0.32 | 0.45% | 0.86 |
| validation | stress | 11 | $0.52 | $0.17 | 0.46% | 0.50 |
| validation | severe | 11 | $0.19 | $0.06 | 0.36% | 0.20 |
| retrospective_evaluation | base | 9 | $-2.62 | $-0.33 | 0.72% | -2.57 |
| retrospective_evaluation | stress | 9 | $-2.74 | $-0.34 | 0.75% | -2.76 |
| retrospective_evaluation | severe | 9 | $-2.86 | $-0.36 | 0.77% | -2.94 |

## Diagnostics

- Stress route/direction: `{'DEFENSE': {'trades': 27, 'net_pnl': -2.451732292782708, 'wins': 8}, 'IFVG': {'trades': 1, 'net_pnl': -0.5, 'wins': 0}, 'LONG': {'trades': 10, 'net_pnl': -1.146477456753587, 'wins': 3}, 'SHORT': {'trades': 18, 'net_pnl': -1.8052548360291212, 'wins': 5}}`.
- Raw candidates: `{'BTCUSDT': 13, 'ETHUSDT': 9, 'SOLUSDT': 8}`.
- State machine: `{'BTCUSDT': {'zones': 1084, 'touched': 1012, 'defense_without_liquidity_sweep': 548, 'invalidated_by_close': 310, 'ifvg_failed_reclaim': 55, 'ifvg_first_retest_no_rejection': 210, 'ifvg_without_liquidity_sweep': 43, 'expired': 78, 'liquidity_sweep_seen': 236, 'defense_armed': 154, 'break_confirmed': 125, 'confluence_veto': 112, 'ifvg_armed': 2, 'confirmation_expired': 24, 'signals_defense': 12, 'signals_long': 5, 'defense_failed_to_ifvg': 7, 'signals_short': 8, 'signals_ifvg': 1, 'deduplicated_signals': 13, 'config': {'formation_minutes': 60, 'confirmation_minutes': 15, 'atr_period': 14, 'volume_lookback': 20, 'displacement_atr': 0.8, 'displacement_volume': 1.15, 'min_gap_atr': 0.05, 'max_gap_atr': 1.25, 'max_zone_age_hours': 120, 'break_buffer_atr': 0.03, 'reaction_body_atr': 0.1, 'confirmation_window_bars': 3, 'ema4h_span': 50, 'oi_lookback_minutes': 60, 'min_oi_change_pct': 0.05, 'long_taker_ratio': 0.52, 'short_taker_ratio': 0.48, 'min_relative_volume': 1.0, 'max_metrics_age_minutes': 15.0, 'min_micro_confluence': 2, 'require_liquidity_sweep': True, 'liquidity_lookback_bars': 20, 'liquidity_sweep_atr': 0.02, 'stop_buffer_atr': 0.15, 'minimum_stop_atr': 0.5, 'maximum_stop_atr': 4.0, 'target_r': 2.5, 'max_hold_minutes': 720}}, 'ETHUSDT': {'zones': 1053, 'touched': 968, 'defense_without_liquidity_sweep': 525, 'liquidity_sweep_seen': 245, 'defense_armed': 137, 'break_confirmed': 106, 'confluence_veto': 97, 'invalidated_by_close': 306, 'ifvg_first_retest_no_rejection': 208, 'expired': 94, 'ifvg_without_liquidity_sweep': 57, 'defense_failed_to_ifvg': 14, 'ifvg_failed_reclaim': 43, 'confirmation_expired': 20, 'signals_defense': 9, 'signals_long': 3, 'ifvg_armed': 3, 'signals_short': 6, 'deduplicated_signals': 9, 'config': {'formation_minutes': 60, 'confirmation_minutes': 15, 'atr_period': 14, 'volume_lookback': 20, 'displacement_atr': 0.8, 'displacement_volume': 1.15, 'min_gap_atr': 0.05, 'max_gap_atr': 1.25, 'max_zone_age_hours': 120, 'break_buffer_atr': 0.03, 'reaction_body_atr': 0.1, 'confirmation_window_bars': 3, 'ema4h_span': 50, 'oi_lookback_minutes': 60, 'min_oi_change_pct': 0.05, 'long_taker_ratio': 0.52, 'short_taker_ratio': 0.48, 'min_relative_volume': 1.0, 'max_metrics_age_minutes': 15.0, 'min_micro_confluence': 2, 'require_liquidity_sweep': True, 'liquidity_lookback_bars': 20, 'liquidity_sweep_atr': 0.02, 'stop_buffer_atr': 0.15, 'minimum_stop_atr': 0.5, 'maximum_stop_atr': 4.0, 'target_r': 2.5, 'max_hold_minutes': 720}}, 'SOLUSDT': {'zones': 1071, 'touched': 996, 'defense_without_liquidity_sweep': 538, 'invalidated_by_close': 304, 'ifvg_first_retest_no_rejection': 199, 'liquidity_sweep_seen': 249, 'expired': 83, 'ifvg_failed_reclaim': 45, 'defense_armed': 154, 'break_confirmed': 127, 'confluence_veto': 118, 'ifvg_without_liquidity_sweep': 57, 'defense_failed_to_ifvg': 10, 'ifvg_armed': 4, 'confirmation_expired': 21, 'signals_defense': 8, 'signals_long': 2, 'stop_too_wide': 1, 'signals_short': 6, 'deduplicated_signals': 8, 'config': {'formation_minutes': 60, 'confirmation_minutes': 15, 'atr_period': 14, 'volume_lookback': 20, 'displacement_atr': 0.8, 'displacement_volume': 1.15, 'min_gap_atr': 0.05, 'max_gap_atr': 1.25, 'max_zone_age_hours': 120, 'break_buffer_atr': 0.03, 'reaction_body_atr': 0.1, 'confirmation_window_bars': 3, 'ema4h_span': 50, 'oi_lookback_minutes': 60, 'min_oi_change_pct': 0.05, 'long_taker_ratio': 0.52, 'short_taker_ratio': 0.48, 'min_relative_volume': 1.0, 'max_metrics_age_minutes': 15.0, 'min_micro_confluence': 2, 'require_liquidity_sweep': True, 'liquidity_lookback_bars': 20, 'liquidity_sweep_atr': 0.02, 'stop_buffer_atr': 0.15, 'minimum_stop_atr': 0.5, 'maximum_stop_atr': 4.0, 'target_r': 2.5, 'max_hold_minutes': 720}}}`.
- Lookback neighbors: `{'12': {'signals': 37, 'trades': 35, 'net_pnl': -3.4381207956898834, 'profit_factor': 0.6713490298035509}, '32': {'signals': 21, 'trades': 19, 'net_pnl': -1.6969983563702158, 'profit_factor': 0.7204726424781135}}`.
- Stop-buffer neighbors: `{'0.1': {'signals': 30, 'trades': 28, 'net_pnl': -2.971752685705269, 'profit_factor': 0.656241475799685}, '0.2': {'signals': 30, 'trades': 28, 'net_pnl': -2.6556440000151156, 'profit_factor': 0.681928939266864}}`.
- Leave-one-out: `{'BTCUSDT': 0.06227169615169714, 'ETHUSDT': -4.637908998553428, 'SOLUSDT': -1.8278272831636855}`.
- Bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': -6.234632211497922, 'p50_terminal_pnl': -3.0978891016565626, 'p90_terminal_pnl': 0.5851579540333606, 'observed_terminal_pnl': -2.951732292782708}`.

**Decision: REJECTED_AT_HISTORICAL_GATE.**

S104 stress average on $500: **$-0.18/month**. This is a historical simulation, not a forecast.
