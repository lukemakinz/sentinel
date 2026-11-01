"""H1 Trend Pullback v1 — causal, research-only signal engine.

This is deliberately not another oscillator dip, market breakout entry or
generic order-block touch.  It requires an established 4h/1h trend, a 15m
displacement through a prior extreme, the first orderly retest of that exact
breakout level, a directional 15m rejection and a closed 5m structure break.
The order then waits at the breakout zone; it is never chased at market.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class H1TrendPullbackConfig:
    name: str = 'H1_TREND_PULLBACK_V1'
    entry_mode: str = 'breakout_edge'
    breakout_lookback: int = 20
    displacement_body_atr: float = 0.80
    displacement_volume_multiple: float = 1.20
    breakout_buffer_atr: float = 0.05
    zone_half_width_atr: float = 0.10
    stop_buffer_atr: float = 0.15
    zone_ttl_bars: int = 8
    confirmation_body_atr: float = 0.25
    h1_adx_minimum: float = 20.0
    h4_adx_minimum: float = 18.0
    minimum_stop_pct: float = 0.60
    maximum_stop_pct: float = 1.25
    first_entry_hour_utc: int = 6
    last_entry_hour_utc: int = 18
    limit_ttl_minutes: int = 30
    target_r: float = 1.50

    def __post_init__(self) -> None:
        if self.breakout_lookback < 10 or self.zone_ttl_bars < 1:
            raise ValueError('H1 lookback and zone TTL are too short')
        if not (0 < self.breakout_buffer_atr < self.displacement_body_atr):
            raise ValueError('Invalid H1 breakout/displacement geometry')
        if not (0 < self.zone_half_width_atr < 0.5 and 0 <= self.stop_buffer_atr < 1):
            raise ValueError('Invalid H1 zone/stop buffer')
        if not (0 < self.minimum_stop_pct < self.maximum_stop_pct < 5):
            raise ValueError('Invalid H1 stop-percent contract')
        if not (0 <= self.first_entry_hour_utc < self.last_entry_hour_utc <= 24):
            raise ValueError('Invalid H1 UTC session')
        if self.limit_ttl_minutes <= 0 or self.target_r <= 1:
            raise ValueError('Invalid H1 execution contract')
        if self.entry_mode not in {'breakout_edge', 'confirmation_body_midpoint'}:
            raise ValueError('Invalid H1 entry mode')

    def execution(self) -> ScalpConfig:
        """Frozen P0 execution used to test entry edge before P1/P2."""
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=0.75,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.5,
            max_hold_minutes=240,
            risk_fraction=0.0020,
            max_notional_equity=0.50,
            daily_loss_fraction=0.006,
            fee_bps=5.0,
            slippage_bps=2.0,
            # At 1.5R target this enforces estimated round-trip costs <= 0.25R.
            min_reward_cost_ratio=6.0,
            leverage=3.0,
            max_margin_fraction=0.10,
            margin_safety_reserve=0.01,
            maker_fee_bps=2.0,
            limit_penetration_bps=2.0,
            fixed_margin_usd=25.0,
            fixed_risk_usd=0.50,
            weekly_loss_fraction=0.018,
            drawdown_halt_fraction=0.06,
            drawdown_risk_scale_fraction=0.04,
            max_positions=1,
        )


def _trend_frame(bars: pd.DataFrame, *, adx_minimum: float) -> pd.DataFrame:
    close = bars.close.to_numpy(float)
    ema20 = talib.EMA(close, timeperiod=20)
    ema50 = talib.EMA(close, timeperiod=50)
    adx = talib.ADX(
        bars.high.to_numpy(float), bars.low.to_numpy(float), close, timeperiod=14,
    )
    frame = pd.DataFrame(index=bars.index)
    frame['long'] = (
        (close > ema20) & (ema20 > ema50)
        & (pd.Series(ema20, index=bars.index) > pd.Series(ema20, index=bars.index).shift(3))
        & (adx >= adx_minimum)
    )
    frame['short'] = (
        (close < ema20) & (ema20 < ema50)
        & (pd.Series(ema20, index=bars.index) < pd.Series(ema20, index=bars.index).shift(3))
        & (adx >= adx_minimum)
    )
    frame['adx'] = adx
    return frame


def build_h1_features(minutes: pd.DataFrame, config: H1TrendPullbackConfig) -> pd.DataFrame:
    """Build closed-bar features. Every 15m row is actionable at its index."""
    bars = resample_closed(minutes, 15)
    close = bars.close.to_numpy(float)
    bars['atr'] = talib.ATR(
        bars.high.to_numpy(float), bars.low.to_numpy(float), close, timeperiod=14,
    )
    bars['volume_baseline'] = (
        bars.volume.shift(1).rolling(config.breakout_lookback).median()
    )
    bars['prior_high'] = bars.high.shift(1).rolling(config.breakout_lookback).max()
    bars['prior_low'] = bars.low.shift(1).rolling(config.breakout_lookback).min()
    body = (bars.close - bars.open).abs()
    candle_range = (bars.high - bars.low).replace(0.0, np.nan)
    close_location = (bars.close - bars.low) / candle_range

    hourly = resample_closed(minutes, 60)
    four_hour = resample_closed(minutes, 240)
    h1 = _trend_frame(hourly, adx_minimum=config.h1_adx_minimum)
    h4 = _trend_frame(four_hour, adx_minimum=config.h4_adx_minimum)
    for label, frame in (('h1', h1), ('h4', h4)):
        for field in ('long', 'short', 'adx'):
            bars[f'{label}_{field}'] = frame[field].reindex(
                bars.index, method='ffill',
            ).infer_objects(copy=False)
    bars[['h1_long', 'h1_short', 'h4_long', 'h4_short']] = bars[
        ['h1_long', 'h1_short', 'h4_long', 'h4_short']
    ].fillna(False).astype(bool)

    volume_ok = bars.volume >= config.displacement_volume_multiple * bars.volume_baseline
    bars['long_displacement'] = (
        bars.h1_long & bars.h4_long & volume_ok
        & (bars.close >= bars.prior_high + config.breakout_buffer_atr * bars.atr)
        & ((bars.close - bars.open) >= config.displacement_body_atr * bars.atr)
        & (close_location >= 0.75)
    ).fillna(False)
    bars['short_displacement'] = (
        bars.h1_short & bars.h4_short & volume_ok
        & (bars.close <= bars.prior_low - config.breakout_buffer_atr * bars.atr)
        & ((bars.open - bars.close) >= config.displacement_body_atr * bars.atr)
        & (close_location <= 0.25)
    ).fillna(False)

    five = resample_closed(minutes, 5)
    five_close = five.close.to_numpy(float)
    five['atr'] = talib.ATR(
        five.high.to_numpy(float), five.low.to_numpy(float), five_close, timeperiod=14,
    )
    five_body = (five.close - five.open).abs()
    five['long_confirm'] = (
        (five.close > five.high.shift(1).rolling(2).max())
        & (five.close > five.open) & (five_body >= 0.15 * five.atr)
    ).fillna(False)
    five['short_confirm'] = (
        (five.close < five.low.shift(1).rolling(2).min())
        & (five.close < five.open) & (five_body >= 0.15 * five.atr)
    ).fillna(False)
    bars['five_long_confirm'] = five.long_confirm.reindex(
        bars.index, method='ffill',
    ).fillna(False).astype(bool)
    bars['five_short_confirm'] = five.short_confirm.reindex(
        bars.index, method='ffill',
    ).fillna(False).astype(bool)
    return bars


def generate_h1_signals(
    bars: pd.DataFrame,
    config: H1TrendPullbackConfig,
    symbol: str,
) -> list[dict]:
    """Track one breakout zone per side and emit only a confirmed retest."""
    active: dict[int, dict | None] = {1: None, -1: None}
    records: list[dict] = []
    for i, (timestamp, bar) in enumerate(bars.iterrows()):
        if not np.isfinite(bar.get('atr', np.nan)):
            continue

        for side in (1, -1):
            zone = active[side]
            if zone is None or i > zone['expires']:
                active[side] = None
                continue
            if i <= zone['created']:
                continue

            invalid = (
                bar.close < zone['stop'] if side == 1
                else bar.close > zone['stop']
            )
            if invalid:
                active[side] = None
                continue
            touched = bar.low <= zone['high'] and bar.high >= zone['low']
            if not touched:
                continue
            directional_close = (
                bar.close > zone['high'] and bar.close > bar.open
                if side == 1
                else bar.close < zone['low'] and bar.close < bar.open
            )
            body_ok = abs(bar.close - bar.open) >= config.confirmation_body_atr * bar.atr
            five_ok = bool(
                bar.five_long_confirm if side == 1 else bar.five_short_confirm
            )
            htf_ok = bool(
                bar.h1_long and bar.h4_long
                if side == 1 else bar.h1_short and bar.h4_short
            )
            if not (directional_close and body_ok and five_ok and htf_ok):
                continue

            if config.entry_mode == 'confirmation_body_midpoint':
                entry = (float(bar.open) + float(bar.close)) / 2.0
            else:
                entry = zone['high'] if side == 1 else zone['low']
            risk = side * (entry - zone['stop'])
            risk_pct = risk / entry * 100.0
            if not config.minimum_stop_pct <= risk_pct <= config.maximum_stop_pct:
                active[side] = None
                continue
            if not config.first_entry_hour_utc <= timestamp.hour < config.last_entry_hour_utc:
                active[side] = None
                continue

            direction = 'long' if side == 1 else 'short'
            records.append({
                'timestamp': timestamp,
                'side': side,
                'limit_price': float(entry),
                'limit_ttl_minutes': config.limit_ttl_minutes,
                'reference': float(bar.close),
                'stop': float(zone['stop']),
                'atr': float(bar.atr),
                'min_stop_atr': 0.5,
                'max_stop_atr': 4.0,
                'min_target_r': config.target_r,
                'score': 10,
                'setup': config.name.lower(),
                'setup_id': f'{config.name}:{symbol}:{direction}:{timestamp.isoformat()}',
                'evidence': {
                    'breakout_time': zone['breakout_time'].isoformat(),
                    'breakout_level': zone['level'],
                    'risk_pct_at_limit': round(risk_pct, 4),
                    'h1_adx': round(float(bar.h1_adx), 2),
                    'h4_adx': round(float(bar.h4_adx), 2),
                    'entry_session_utc': timestamp.hour,
                    'entry_mode': config.entry_mode,
                },
            })
            active[side] = None

        # New displacement becomes actionable only from the next 15m bar.
        if bool(bar.long_displacement):
            level = float(bar.prior_high)
            half = config.zone_half_width_atr * float(bar.atr)
            active[1] = {
                'low': level - half,
                'high': level + half,
                'stop': float(bar.low - config.stop_buffer_atr * bar.atr),
                'level': level,
                'created': i,
                'expires': i + config.zone_ttl_bars,
                'breakout_time': timestamp,
            }
        if bool(bar.short_displacement):
            level = float(bar.prior_low)
            half = config.zone_half_width_atr * float(bar.atr)
            active[-1] = {
                'low': level - half,
                'high': level + half,
                'stop': float(bar.high + config.stop_buffer_atr * bar.atr),
                'level': level,
                'created': i,
                'expires': i + config.zone_ttl_bars,
                'breakout_time': timestamp,
            }

    return records
