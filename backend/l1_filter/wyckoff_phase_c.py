"""Causal Wyckoff Phase-C spring/test and UTAD/test signals.

The implementation deliberately avoids subjective phase labels.  A signal is
published only after a frozen trading range, a failed boundary auction, a
lower-volume test, and a confirming bar have all completed in that order.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class WyckoffPhaseCConfig:
    name: str = 'S94_wyckoff_phase_c'
    bar_minutes: int = 60
    range_hours: int = 120
    prior_trend_hours: int = 336
    min_prior_trend_fraction: float = 0.03
    support_quantile: float = 0.10
    resistance_quantile: float = 0.90
    min_range_atr: float = 4.0
    max_range_atr: float = 14.0
    max_efficiency_ratio: float = 0.35
    min_touch_clusters: int = 2
    touch_separation_hours: int = 8
    touch_tolerance_atr: float = 0.30
    min_sweep_atr: float = 0.10
    max_sweep_atr: float = 1.25
    sweep_volume_multiple: float = 1.10
    absorption_taker_fraction: float = 0.48
    min_wick_fraction: float = 0.35
    min_test_delay_hours: int = 2
    max_test_delay_hours: int = 24
    test_distance_atr: float = 0.50
    max_test_sweep_extension_atr: float = 0.10
    max_test_to_sweep_volume: float = 0.80
    max_test_volume_multiple: float = 1.00
    confirmation_hours: int = 12
    confirmation_break_atr: float = 0.05
    max_entry_range_fraction: float = 0.45
    confirmation_volume_multiple: float = 0.90
    stop_buffer_atr: float = 0.10
    target_buffer_atr: float = 0.10
    minimum_reward_risk: float = 2.20
    cooldown_hours: int = 48

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=60,
            target_r=3.0,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=72 * 60,
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


def prepare_wyckoff_bars(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    previous = out.close.shift()
    true_range = pd.concat([
        out.high - out.low,
        (out.high - previous).abs(),
        (out.low - previous).abs(),
    ], axis=1).max(axis=1)
    out['atr'] = true_range.rolling(14).mean()
    out['volume_median24'] = out.volume.shift().rolling(24).median()
    out['taker_buy_fraction'] = (
        out.taker_buy_volume / out.volume.replace(0.0, np.nan)
    ).fillna(0.5)
    return out


def _touch_clusters(values: np.ndarray, threshold: float, below: bool, separation: int) -> int:
    hit = values <= threshold if below else values >= threshold
    count, last = 0, -separation
    for i, matched in enumerate(hit):
        if matched and i - last >= separation:
            count += 1
            last = i
    return count


def _range_snapshot(bars: pd.DataFrame, i: int, config: WyckoffPhaseCConfig):
    history = bars.iloc[i - config.range_hours:i]
    row = bars.iloc[i]
    atr = float(row.atr)
    if not np.isfinite(atr) or atr <= 0 or len(history) != config.range_hours:
        return None
    support = float(history.low.quantile(config.support_quantile))
    resistance = float(history.high.quantile(config.resistance_quantile))
    width = resistance - support
    if width <= 0 or not config.min_range_atr <= width / atr <= config.max_range_atr:
        return None
    travel = float(history.close.diff().abs().sum())
    efficiency = abs(float(history.close.iloc[-1] - history.close.iloc[0])) / max(travel, 1e-12)
    if efficiency > config.max_efficiency_ratio:
        return None
    tolerance = config.touch_tolerance_atr * atr
    low_touches = _touch_clusters(
        history.low.to_numpy(), support + tolerance, True,
        config.touch_separation_hours)
    high_touches = _touch_clusters(
        history.high.to_numpy(), resistance - tolerance, False,
        config.touch_separation_hours)
    if min(low_touches, high_touches) < config.min_touch_clusters:
        return None
    return {
        'support': support,
        'resistance': resistance,
        'width': width,
        'atr': atr,
        'efficiency': efficiency,
        'low_touches': low_touches,
        'high_touches': high_touches,
    }


def _sweep_side(row, snapshot, trend_return: float, config: WyckoffPhaseCConfig) -> int:
    atr = snapshot['atr']
    candle_range = max(float(row.high - row.low), 1e-12)
    lower_wick = float(min(row.open, row.close) - row.low) / candle_range
    upper_wick = float(row.high - max(row.open, row.close)) / candle_range
    vol_ratio = float(row.volume / row.volume_median24)
    long_depth = (snapshot['support'] - float(row.low)) / atr
    short_depth = (float(row.high) - snapshot['resistance']) / atr
    long_ok = (
        trend_return <= -config.min_prior_trend_fraction
        and config.min_sweep_atr <= long_depth <= config.max_sweep_atr
        and row.close >= snapshot['support']
        and lower_wick >= config.min_wick_fraction
        and vol_ratio >= config.sweep_volume_multiple
        and row.taker_buy_fraction <= config.absorption_taker_fraction
    )
    short_ok = (
        trend_return >= config.min_prior_trend_fraction
        and config.min_sweep_atr <= short_depth <= config.max_sweep_atr
        and row.close <= snapshot['resistance']
        and upper_wick >= config.min_wick_fraction
        and vol_ratio >= config.sweep_volume_multiple
        and row.taker_buy_fraction >= 1.0 - config.absorption_taker_fraction
    )
    if long_ok == short_ok:
        return 0
    return 1 if long_ok else -1


def _is_test(row, state: dict, config: WyckoffPhaseCConfig) -> bool:
    side, atr = state['side'], state['atr']
    boundary = state['support'] if side == 1 else state['resistance']
    near = (
        row.low <= boundary + config.test_distance_atr * atr
        if side == 1 else row.high >= boundary - config.test_distance_atr * atr
    )
    held = row.close >= boundary if side == 1 else row.close <= boundary
    extreme_ok = (
        row.low >= state['sweep_extreme'] - config.max_test_sweep_extension_atr * atr
        if side == 1 else row.high <= state['sweep_extreme'] + config.max_test_sweep_extension_atr * atr
    )
    return bool(
        near and held and extreme_ok
        and row.volume <= config.max_test_to_sweep_volume * state['sweep_volume']
        and row.volume <= config.max_test_volume_multiple * row.volume_median24
    )


def _confirmation_signal(row, state: dict, config: WyckoffPhaseCConfig):
    side, atr = state['side'], state['atr']
    width = state['resistance'] - state['support']
    test = state['test']
    breakout = (
        row.close >= test['high'] + config.confirmation_break_atr * atr
        if side == 1 else row.close <= test['low'] - config.confirmation_break_atr * atr
    )
    directional = side * (float(row.close) - float(row.open)) > 0
    location = (float(row.close) - state['support']) / width
    location_ok = (
        location <= config.max_entry_range_fraction if side == 1
        else location >= 1.0 - config.max_entry_range_fraction
    )
    volume_ok = row.volume >= config.confirmation_volume_multiple * row.volume_median24
    if not (breakout and directional and location_ok and volume_ok):
        return None

    stop = (
        state['sweep_extreme'] - config.stop_buffer_atr * atr
        if side == 1 else state['sweep_extreme'] + config.stop_buffer_atr * atr
    )
    target = (
        state['resistance'] - config.target_buffer_atr * atr
        if side == 1 else state['support'] + config.target_buffer_atr * atr
    )
    risk = side * (float(row.close) - stop)
    reward = side * (target - float(row.close))
    if risk <= 0 or reward / risk < config.minimum_reward_risk:
        return None
    score = min(100.0, 55.0 + 10.0 * min(2.0, state['sweep_volume_ratio'] - 1.0)
                + 15.0 * min(1.0, 1.0 - test['volume'] / state['sweep_volume'])
                + 10.0 * min(1.0, reward / risk / 3.0)
                + 5.0 * min(1.0, state['touches'] / 4.0))
    return {
        'timestamp': row.name,
        'side': side,
        'atr': atr,
        'stop': float(stop),
        'target_price': float(target),
        'target_boundary': float(target),
        'min_stop_atr': 0.20,
        'max_stop_atr': 3.00,
        'min_target_r': 2.0,
        'score': float(score),
        'setup': 'WYCKOFF_SPRING_TEST' if side == 1 else 'WYCKOFF_UTAD_TEST',
        'setup_id': f'{side}:{state["sweep_time"].isoformat()}:{row.name.isoformat()}',
        'evidence': {
            'support': state['support'],
            'resistance': state['resistance'],
            'sweep_time': state['sweep_time'].isoformat(),
            'test_time': test['time'].isoformat(),
            'sweep_volume_ratio': state['sweep_volume_ratio'],
            'test_to_sweep_volume': test['volume'] / state['sweep_volume'],
            'reward_risk_at_signal_close': reward / risk,
            'range_efficiency': state['efficiency'],
        },
    }


def wyckoff_signals_from_bars(
    bars: pd.DataFrame,
    config: WyckoffPhaseCConfig = WyckoffPhaseCConfig(),
) -> list[dict]:
    required = {'atr', 'volume_median24', 'taker_buy_fraction'}
    if not required.issubset(bars.columns):
        bars = prepare_wyckoff_bars(bars)
    start = max(config.range_hours, config.prior_trend_hours, 24)
    state = None
    cooldown_until = bars.index[0]
    signals = []
    for i in range(start, len(bars)):
        row = bars.iloc[i]
        if not (np.isfinite(row.atr) and np.isfinite(row.volume_median24)
                and row.volume_median24 > 0):
            continue
        now = bars.index[i]
        if state is not None:
            age = i - state['sweep_i']
            if state.get('test') is None:
                if age > config.max_test_delay_hours:
                    state = None
                elif age >= config.min_test_delay_hours and _is_test(row, state, config):
                    state['test'] = {
                        'i': i, 'time': now, 'high': float(row.high),
                        'low': float(row.low), 'volume': float(row.volume),
                    }
                    continue
            else:
                if i - state['test']['i'] > config.confirmation_hours:
                    state = None
                else:
                    signal = _confirmation_signal(row, state, config)
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
        trend_base = float(bars.close.iloc[i - config.prior_trend_hours])
        trend_return = float(row.close / trend_base - 1.0)
        side = _sweep_side(row, snapshot, trend_return, config)
        if not side:
            continue
        state = {
            **snapshot,
            'side': side,
            'sweep_i': i,
            'sweep_time': now,
            'sweep_extreme': float(row.low if side == 1 else row.high),
            'sweep_volume': float(row.volume),
            'sweep_volume_ratio': float(row.volume / row.volume_median24),
            'touches': snapshot['low_touches'] if side == 1 else snapshot['high_touches'],
        }
    return signals


def build_wyckoff_signals(
    minutes: pd.DataFrame,
    config: WyckoffPhaseCConfig = WyckoffPhaseCConfig(),
) -> list[dict]:
    bars = resample_closed(minutes, config.bar_minutes)
    return wyckoff_signals_from_bars(prepare_wyckoff_bars(bars), config)
