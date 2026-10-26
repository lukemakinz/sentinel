"""S55: 4h Donchian breakout with 2.5R, held in hours not minutes.

S48-S54 all lost as 1.0R scalps after costs. This is a different payoff:
close through the prior 4h channel, ATR stop, 2.5R target, 24-36h cap,
no trailing. One attempt per UTC day.

Routes:
  donchian_20 — 20-bar (3.3 day) channel, 36h hold
  donchian_10 — 10-bar (1.7 day) channel, 24h hold
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class Donchian4hConfig:
    name: str = 'S55_donchian_4h'
    route: str = 'donchian_20'
    stop_buffer_atr_mult: float = 0.35
    target_r: float = 2.5

    def __post_init__(self):
        if self.route not in ('donchian_20', 'donchian_10'):
            raise ValueError('Unknown S55 route')
        if self.stop_buffer_atr_mult < 0 or self.target_r <= 1.0:
            raise ValueError('Invalid S55 configuration')

    @property
    def lookback(self) -> int:
        return 20 if self.route == 'donchian_20' else 10

    @property
    def max_hold_minutes(self) -> int:
        return 2160 if self.route == 'donchian_20' else 1440

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=1.0,
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


def donchian_4h_features(minutes: pd.DataFrame, config: Donchian4hConfig) -> pd.DataFrame:
    bars = resample_closed(minutes, 240)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['donchian_high'] = bars.high.shift(1).rolling(
        config.lookback, min_periods=config.lookback).max()
    bars['donchian_low'] = bars.low.shift(1).rolling(
        config.lookback, min_periods=config.lookback).min()
    bars['session_day'] = bars.index.tz_convert('UTC').normalize()
    return bars


def generate_donchian_4h_signals(
    bars: pd.DataFrame,
    config: Donchian4hConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_days = set()
    for row in bars.itertuples():
        day = row.session_day
        if day in used_days:
            continue
        local_atr = float(row.atr)
        if not np.isfinite(local_atr) or local_atr <= 0:
            continue
        if not np.isfinite(row.donchian_high) or not np.isfinite(row.donchian_low):
            continue
        side = None
        stop = None
        if row.close > row.donchian_high:
            side = 1
            stop = float(row.low) - config.stop_buffer_atr_mult * local_atr
        elif row.close < row.donchian_low:
            side = -1
            stop = float(row.high) + config.stop_buffer_atr_mult * local_atr
        if side is None:
            continue
        risk = side * (row.close - stop)
        if risk <= 0:
            continue
        used_days.add(day)
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
            'setup': f'donchian_4h_{config.route}',
            'setup_id': (
                f'S55:{config.route}:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
