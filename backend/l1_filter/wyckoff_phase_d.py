"""Causal Wyckoff Phase-D SOS/SOW followed by LPS/LPSY."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scalp_strategy import ScalpConfig, resample_closed
from .wyckoff_phase_c import _range_snapshot, prepare_wyckoff_bars


@dataclass(frozen=True)
class WyckoffPhaseDConfig:
    name: str = 'S95_wyckoff_phase_d_lps'
    bar_minutes: int = 60
    range_hours: int = 120
    support_quantile: float = 0.10
    resistance_quantile: float = 0.90
    min_range_atr: float = 4.0
    max_range_atr: float = 14.0
    max_efficiency_ratio: float = 0.35
    min_touch_clusters: int = 2
    touch_separation_hours: int = 8
    touch_tolerance_atr: float = 0.30
    breakout_close_atr: float = 0.20
    max_breakout_close_atr: float = 2.00
    breakout_spread_atr: float = 0.80
    breakout_volume_multiple: float = 1.25
    breakout_taker_fraction: float = 0.52
    min_close_location: float = 0.70
    min_test_delay_hours: int = 2
    max_test_delay_hours: int = 48
    test_distance_atr: float = 0.35
    max_test_failure_atr: float = 0.15
    max_test_to_breakout_volume: float = 0.75
    max_test_volume_multiple: float = 0.90
    max_test_spread_atr: float = 1.00
    confirmation_hours: int = 8
    confirmation_break_atr: float = 0.05
    confirmation_volume_multiple: float = 0.90
    maximum_chase_atr: float = 1.50
    stop_buffer_atr: float = 0.15
    minimum_reward_risk: float = 2.50
    cooldown_hours: int = 72

    # _range_snapshot accepts the Phase-C config by duck typing and needs this
    # attribute even though Phase D has no prior-trend gate.
    prior_trend_hours: int = 0

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=60,
            target_r=3.0,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=7 * 24 * 60,
            risk_fraction=0.004,
            max_notional_equity=1.0,
            daily_loss_fraction=0.015,
            weekly_loss_fraction=0.030,
            drawdown_risk_scale_fraction=0.040,
            drawdown_halt_fraction=0.060,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=3.0,
            leverage=3.0,
            max_margin_fraction=0.25,
            margin_safety_reserve=0.01,
            fixed_risk_usd=2.0,
            max_positions=1,
        )


def _breakout_side(row, snapshot, config: WyckoffPhaseDConfig) -> int:
    atr = snapshot['atr']
    spread = float(row.high - row.low)
    if spread < config.breakout_spread_atr * atr:
        return 0
    vol_ratio = float(row.volume / row.volume_median24)
    if vol_ratio < config.breakout_volume_multiple:
        return 0
    close_location = float((row.close - row.low) / max(spread, 1e-12))
    long_depth = float((row.close - snapshot['resistance']) / atr)
    short_depth = float((snapshot['support'] - row.close) / atr)
    long_ok = (
        config.breakout_close_atr <= long_depth <= config.max_breakout_close_atr
        and close_location >= config.min_close_location
        and row.taker_buy_fraction >= config.breakout_taker_fraction
    )
    short_ok = (
        config.breakout_close_atr <= short_depth <= config.max_breakout_close_atr
        and close_location <= 1.0 - config.min_close_location
        and row.taker_buy_fraction <= 1.0 - config.breakout_taker_fraction
    )
    if long_ok == short_ok:
        return 0
    return 1 if long_ok else -1


def _is_lps(row, state, config: WyckoffPhaseDConfig) -> bool:
    side, atr, boundary = state['side'], state['atr'], state['boundary']
    near = (
        row.low <= boundary + config.test_distance_atr * atr
        if side == 1 else row.high >= boundary - config.test_distance_atr * atr
    )
    holds = (
        row.low >= boundary - config.max_test_failure_atr * atr and row.close >= boundary
        if side == 1 else
        row.high <= boundary + config.max_test_failure_atr * atr and row.close <= boundary
    )
    return bool(
        near and holds
        and row.volume <= config.max_test_to_breakout_volume * state['breakout_volume']
        and row.volume <= config.max_test_volume_multiple * row.volume_median24
        and row.high - row.low <= config.max_test_spread_atr * atr
    )


def _confirmation(row, state, config: WyckoffPhaseDConfig):
    side, atr, boundary = state['side'], state['atr'], state['boundary']
    test = state['test']
    breaks = (
        row.close >= test['high'] + config.confirmation_break_atr * atr
        if side == 1 else row.close <= test['low'] - config.confirmation_break_atr * atr
    )
    directional = side * (float(row.close) - float(row.open)) > 0
    chase = side * (float(row.close) - boundary) / atr
    if not (breaks and directional
            and row.volume >= config.confirmation_volume_multiple * row.volume_median24
            and chase <= config.maximum_chase_atr):
        return None
    stop = (
        test['low'] - config.stop_buffer_atr * atr
        if side == 1 else test['high'] + config.stop_buffer_atr * atr
    )
    target = boundary + side * state['width']
    risk = side * (float(row.close) - stop)
    reward = side * (target - float(row.close))
    if risk <= 0 or reward / risk < config.minimum_reward_risk:
        return None
    score = min(100.0, 60.0
                + 10.0 * min(1.0, state['breakout_volume_ratio'] - 1.0)
                + 15.0 * min(1.0, 1.0 - test['volume'] / state['breakout_volume'])
                + 10.0 * min(1.0, reward / risk / 4.0))
    return {
        'timestamp': row.name,
        'side': side,
        'atr': atr,
        'stop': float(stop),
        'target_price': float(target),
        'target_boundary': float(target),
        'min_stop_atr': 0.20,
        'max_stop_atr': 2.00,
        'min_target_r': 2.0,
        'score': float(score),
        'setup': 'WYCKOFF_SOS_LPS' if side == 1 else 'WYCKOFF_SOW_LPSY',
        'setup_id': f'{side}:{state["breakout_time"].isoformat()}:{row.name.isoformat()}',
        'evidence': {
            'range_support': state['support'],
            'range_resistance': state['resistance'],
            'breakout_time': state['breakout_time'].isoformat(),
            'test_time': test['time'].isoformat(),
            'test_to_breakout_volume': test['volume'] / state['breakout_volume'],
            'measured_move_reward_risk': reward / risk,
        },
    }


def wyckoff_phase_d_signals_from_bars(
    bars: pd.DataFrame,
    config: WyckoffPhaseDConfig = WyckoffPhaseDConfig(),
) -> list[dict]:
    required = {'atr', 'volume_median24', 'taker_buy_fraction'}
    if not required.issubset(bars.columns):
        bars = prepare_wyckoff_bars(bars)
    state = None
    signals = []
    cooldown_until = bars.index[0]
    for i in range(max(config.range_hours, 24), len(bars)):
        row, now = bars.iloc[i], bars.index[i]
        if not (np.isfinite(row.atr) and np.isfinite(row.volume_median24)
                and row.volume_median24 > 0):
            continue
        if state is not None:
            age = i - state['breakout_i']
            if state.get('test') is None:
                if age > config.max_test_delay_hours:
                    state = None
                elif age >= config.min_test_delay_hours and _is_lps(row, state, config):
                    state['test'] = {
                        'i': i, 'time': now, 'high': float(row.high),
                        'low': float(row.low), 'volume': float(row.volume),
                    }
                    continue
            else:
                if i - state['test']['i'] > config.confirmation_hours:
                    state = None
                else:
                    signal = _confirmation(row, state, config)
                    if signal is not None:
                        signals.append(signal)
                        cooldown_until = now + pd.Timedelta(hours=config.cooldown_hours)
                        state = None
                        continue
        if state is not None or now < cooldown_until:
            continue
        snapshot = _range_snapshot(bars, i, config)
        if snapshot is None:
            continue
        side = _breakout_side(row, snapshot, config)
        if not side:
            continue
        state = {
            **snapshot,
            'side': side,
            'boundary': snapshot['resistance'] if side == 1 else snapshot['support'],
            'breakout_i': i,
            'breakout_time': now,
            'breakout_volume': float(row.volume),
            'breakout_volume_ratio': float(row.volume / row.volume_median24),
        }
    return signals


def build_wyckoff_phase_d_signals(
    minutes: pd.DataFrame,
    config: WyckoffPhaseDConfig = WyckoffPhaseDConfig(),
) -> list[dict]:
    bars = prepare_wyckoff_bars(resample_closed(minutes, config.bar_minutes))
    return wyckoff_phase_d_signals_from_bars(bars, config)
