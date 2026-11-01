# S103 — FVG defense / IFVG inversion decision tree

Frozen protocol: `eeb17ddc8daad4dcd1a83acf42a34f503388b7a90f9d84f6819d0b4cd51aca2a`.

**Historical research only. Live trading remains disabled.**

A touch is never an entry. The model waits for closed-candle evidence of either defense or inversion, then enters at the next 5m open.

| Full replay | Trades | WR | PF | PnL | Return | $/month | DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| base | 104 | 27.9% | 0.6460191467898545 | $-12.23 | -2.45% | $-0.76 | 3.38% |
| stress | 104 | 26.0% | 0.5468002004575767 | $-15.79 | -3.16% | $-0.99 | 3.77% |
| severe | 103 | 25.2% | 0.45907443483474936 | $-18.72 | -3.74% | $-1.17 | 4.11% |

| Period | Costs | Trades | PnL | Return on start NAV | $/month | DD | Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|
| development | base | 31 | $-1.13 | -0.23% | $-0.23 | 0.78% | -0.48 |
| development | stress | 31 | $-2.79 | -0.56% | $-0.55 | 0.89% | -1.32 |
| development | severe | 30 | $-3.24 | -0.65% | $-0.64 | 0.88% | -1.64 |
| validation | base | 34 | $-4.62 | -0.93% | $-1.53 | 1.74% | -2.63 |
| validation | stress | 34 | $-5.41 | -1.09% | $-1.79 | 1.99% | -3.22 |
| validation | severe | 34 | $-6.07 | -1.22% | $-2.01 | 2.11% | -3.74 |
| retrospective_evaluation | base | 39 | $-6.48 | -1.31% | $-0.81 | 3.24% | -2.10 |
| retrospective_evaluation | stress | 39 | $-7.60 | -1.54% | $-0.95 | 3.65% | -2.64 |
| retrospective_evaluation | severe | 39 | $-9.41 | -1.92% | $-1.18 | 4.04% | -3.61 |

## Attribution and robustness

- Stress route/direction breakdown: `{'DEFENSE': {'trades': 94, 'net_pnl': -15.695281231247293, 'wins': 23}, 'IFVG': {'trades': 10, 'net_pnl': -0.09820949275115254, 'wins': 4}, 'LONG': {'trades': 40, 'net_pnl': -4.378141861523375, 'wins': 12}, 'SHORT': {'trades': 64, 'net_pnl': -11.41534886247507, 'wins': 15}}`.
- Raw state-machine diagnostics: `{'BTCUSDT': {'zones': 1084, 'touched': 1012, 'defense_armed': 702, 'break_confirmed': 605, 'confluence_veto': 556, 'defense_failed_to_ifvg': 45, 'ifvg_first_retest_no_rejection': 236, 'invalidated_by_close': 310, 'ifvg_failed_reclaim': 61, 'ifvg_armed': 51, 'expired': 78, 'ifvg_rejection_failed': 5, 'confirmation_expired': 98, 'signals_defense': 44, 'signals_long': 19, 'signals_ifvg': 4, 'signals_short': 29, 'stop_too_wide': 1, 'deduplicated_signals': 48, 'config': {'formation_minutes': 60, 'confirmation_minutes': 15, 'atr_period': 14, 'volume_lookback': 20, 'displacement_atr': 0.8, 'displacement_volume': 1.15, 'min_gap_atr': 0.05, 'max_gap_atr': 1.25, 'max_zone_age_hours': 120, 'break_buffer_atr': 0.03, 'reaction_body_atr': 0.1, 'confirmation_window_bars': 3, 'ema4h_span': 50, 'oi_lookback_minutes': 60, 'min_oi_change_pct': 0.05, 'long_taker_ratio': 0.52, 'short_taker_ratio': 0.48, 'min_relative_volume': 1.0, 'max_metrics_age_minutes': 15.0, 'min_micro_confluence': 2, 'stop_buffer_atr': 0.15, 'minimum_stop_atr': 0.5, 'maximum_stop_atr': 4.0, 'target_r': 2.5, 'max_hold_minutes': 720}}, 'ETHUSDT': {'zones': 1053, 'touched': 968, 'defense_armed': 662, 'break_confirmed': 574, 'confluence_veto': 540, 'confirmation_expired': 96, 'invalidated_by_close': 306, 'ifvg_first_retest_no_rejection': 234, 'expired': 96, 'ifvg_armed': 66, 'defense_failed_to_ifvg': 54, 'ifvg_failed_reclaim': 49, 'ifvg_rejection_failed': 4, 'signals_defense': 31, 'signals_long': 11, 'signals_ifvg': 3, 'signals_short': 23, 'deduplicated_signals': 34, 'config': {'formation_minutes': 60, 'confirmation_minutes': 15, 'atr_period': 14, 'volume_lookback': 20, 'displacement_atr': 0.8, 'displacement_volume': 1.15, 'min_gap_atr': 0.05, 'max_gap_atr': 1.25, 'max_zone_age_hours': 120, 'break_buffer_atr': 0.03, 'reaction_body_atr': 0.1, 'confirmation_window_bars': 3, 'ema4h_span': 50, 'oi_lookback_minutes': 60, 'min_oi_change_pct': 0.05, 'long_taker_ratio': 0.52, 'short_taker_ratio': 0.48, 'min_relative_volume': 1.0, 'max_metrics_age_minutes': 15.0, 'min_micro_confluence': 2, 'stop_buffer_atr': 0.15, 'minimum_stop_atr': 0.5, 'maximum_stop_atr': 4.0, 'target_r': 2.5, 'max_hold_minutes': 720}}, 'SOLUSDT': {'zones': 1071, 'touched': 996, 'defense_armed': 692, 'break_confirmed': 618, 'confluence_veto': 574, 'invalidated_by_close': 304, 'ifvg_first_retest_no_rejection': 224, 'expired': 84, 'ifvg_failed_reclaim': 48, 'confirmation_expired': 95, 'ifvg_armed': 65, 'defense_failed_to_ifvg': 43, 'signals_ifvg': 5, 'signals_long': 17, 'signals_defense': 38, 'stop_too_wide': 1, 'signals_short': 26, 'ifvg_rejection_failed': 1, 'deduplicated_signals': 43, 'config': {'formation_minutes': 60, 'confirmation_minutes': 15, 'atr_period': 14, 'volume_lookback': 20, 'displacement_atr': 0.8, 'displacement_volume': 1.15, 'min_gap_atr': 0.05, 'max_gap_atr': 1.25, 'max_zone_age_hours': 120, 'break_buffer_atr': 0.03, 'reaction_body_atr': 0.1, 'confirmation_window_bars': 3, 'ema4h_span': 50, 'oi_lookback_minutes': 60, 'min_oi_change_pct': 0.05, 'long_taker_ratio': 0.52, 'short_taker_ratio': 0.48, 'min_relative_volume': 1.0, 'max_metrics_age_minutes': 15.0, 'min_micro_confluence': 2, 'stop_buffer_atr': 0.15, 'minimum_stop_atr': 0.5, 'maximum_stop_atr': 4.0, 'target_r': 2.5, 'max_hold_minutes': 720}}}`.
- Leave-one-symbol-out stress PnL: `{'BTCUSDT': -5.1147223487215, 'ETHUSDT': -12.341200194408998, 'SOLUSDT': -14.285035083674245}`.
- Micro-confluence neighbors stress PnL: `{'1': -24.344810588019186, '3': -4.31044382791157}`.
- Target neighbors stress PnL: `{'2.0': -18.237599989395846, '3.0': -13.641181385606387}`.
- 28-day bootstrap: `{'method': 'circular_28d_blocks', 'samples': 5000, 'p10_terminal_pnl': -22.94274717848984, 'p50_terminal_pnl': -15.737491533330171, 'p90_terminal_pnl': -9.089698626865205, 'observed_terminal_pnl': -15.793490723998445}`.

**Decision: REJECTED_AT_HISTORICAL_GATE.**

Stress historical average on $500: **$-0.99/month**. This is a replay estimate, not a forecast or guarantee.
