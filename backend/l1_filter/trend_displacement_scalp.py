"""S53: trade with-trend displacement, not the pullback and not the range fade.

S48 lost by taking every EMA pullback. S49-S52 lost by fading session
geometry. A professional impulse trader takes the expansion candle itself:
large body, close through a short lookback extreme, volume expansion, 4h
trend agreement. One attempt per 4h bucket. Early profit: 1.0R, no trail.

Routes:
  displacement_5m   — 5m impulse, 45-minute time stop
  displacement_15m  — 15m impulse, 90-minute time stop
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .oi_state_transition_scalp import _confirmed_structure
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class TrendDisplacementConfig:
    name: str = 'S53_trend_displacement'
    route: str = 'displacement_5m'
    pivot_width: int = 2
    lookback_bars: int = 12
    body_atr_mult: float = 0.80
    close_location: float = 0.75
    volume_mult: float = 1.5
    volume_lookback: int = 20
    stop_buffer_atr_mult: float = 0.10
    target_r: float = 1.0

    def __post_init__(self):
        if self.route not in ('displacement_5m', 'displacement_15m'):
            raise ValueError('Unknown S53 route')
        if (self.pivot_width < 1 or self.lookback_bars < 4
                or self.body_atr_mult <= 0 or not 0.5 < self.close_location < 1
                or self.volume_mult <= 0 or self.volume_lookback < 5
                or self.stop_buffer_atr_mult < 0 or self.target_r <= 0):
            raise ValueError('Invalid S53 configuration')

    @property
    def minutes(self) -> int:
        return 5 if self.route == 'displacement_5m' else 15

    @property
    def max_hold_minutes(self) -> int:
        return 45 if self.route == 'displacement_5m' else 90

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=self.minutes,
            target_r=self.target_r,
            partial_r=0.5,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=self.max_hold_minutes,
            risk_fraction=0.002,
            max_notional_equity=0.5,
            daily_loss_fraction=0.006,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=2.0,
            leverage=5.0,
            max_margin_fraction=0.1,
            margin_safety_reserve=0.01,
            maker_fee_bps=5.0,
            limit_penetration_bps=0.0,
            fixed_margin_usd=25.0,
            fixed_risk_usd=0.5,
        )


def trend_displacement_features(
    minutes: pd.DataFrame,
    config: TrendDisplacementConfig,
) -> pd.DataFrame:
    bars = resample_closed(minutes, config.minutes)
    four_hour = resample_closed(minutes, 240)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['regime'] = _confirmed_structure(
        four_hour, config.pivot_width
    ).reindex(bars.index, method='ffill').fillna(0).astype(int)
    bars['prior_high'] = bars.high.shift(1).rolling(
        config.lookback_bars, min_periods=config.lookback_bars).max()
    bars['prior_low'] = bars.low.shift(1).rolling(
        config.lookback_bars, min_periods=config.lookback_bars).min()
    bars['volume_median'] = bars.volume.shift(1).rolling(
        config.volume_lookback, min_periods=config.volume_lookback).median()
    bars['bucket'] = bars.index.floor('4h')
    return bars


def generate_trend_displacement_signals(
    bars: pd.DataFrame,
    config: TrendDisplacementConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_buckets = set()
    for row in bars.itertuples():
        bucket = row.bucket
        if bucket in used_buckets:
            continue
        regime = int(row.regime)
        if regime == 0:
            continue
        local_atr = float(row.atr)
        if not np.isfinite(local_atr) or local_atr <= 0:
            continue
        if not np.isfinite(row.prior_high) or not np.isfinite(row.prior_low):
            continue
        vol_med = float(row.volume_median)
        if not np.isfinite(vol_med) or vol_med <= 0:
            continue
        if row.volume < config.volume_mult * vol_med:
            continue
        body = abs(row.close - row.open)
        if body < config.body_atr_mult * local_atr:
            continue
        bar_range = row.high - row.low
        if bar_range <= 0:
            continue
        location = (row.close - row.low) / bar_range
        side = None
        stop = None
        if (regime == 1 and row.close > row.prior_high
                and location >= config.close_location):
            side = 1
            stop = float(row.low) - config.stop_buffer_atr_mult * local_atr
        elif (regime == -1 and row.close < row.prior_low
                and location <= 1.0 - config.close_location):
            side = -1
            stop = float(row.high) + config.stop_buffer_atr_mult * local_atr
        if side is None:
            continue
        risk = side * (row.close - stop)
        if risk <= 0:
            continue
        used_buckets.add(bucket)
        direction = 'long' if side == 1 else 'short'
        records.append({
            'timestamp': row.Index,
            'side': side,
            'reference': float(row.close),
            'stop': float(stop),
            'atr': local_atr,
            'min_stop_atr': 0.2,
            'max_stop_atr': 8.0,
            'score': 7,
            'setup': f'trend_displacement_{config.route}',
            'setup_id': (
                f'S53:{config.route}:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
