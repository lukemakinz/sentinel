"""S64 H1: daily Donchian-20 turtle, uncapped R, multi-day hold.

Not S55 (4h channel, 2.5R) and not S58 (daily TSMOM, 2.5R).
Close through the prior 20-day high/low, 1.5 ATR stop, ~15-day hold,
far target so TIME/STOP dominate. $10 risk, halt stack sized for day/swing.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class DailyTurtleConfig:
    name: str = 'S64_daily_turtle_20'
    lookback: int = 20
    stop_atr_mult: float = 1.50
    target_r: float = 12.0
    max_hold_days: int = 15

    def __post_init__(self):
        if self.lookback < 10 or self.stop_atr_mult <= 0 or self.target_r < 10:
            raise ValueError('Invalid S64 turtle configuration')
        if self.max_hold_days < 10:
            raise ValueError('Turtle hold must be multi-day')

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=self.max_hold_days * 1440,
            risk_fraction=0.04,
            max_notional_equity=8.0,
            daily_loss_fraction=0.10,
            weekly_loss_fraction=0.15,
            drawdown_halt_fraction=0.25,
            drawdown_risk_scale_fraction=0.12,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=0.5,
            leverage=5.0,
            max_margin_fraction=0.5,
            margin_safety_reserve=0.01,
            maker_fee_bps=5.0,
            limit_penetration_bps=0.0,
            fixed_margin_usd=None,
            fixed_risk_usd=10.0,
        )


def daily_turtle_features(minutes: pd.DataFrame, config: DailyTurtleConfig) -> pd.DataFrame:
    bars = resample_closed(minutes, 1440)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['donchian_high'] = bars.high.shift(1).rolling(
        config.lookback, min_periods=config.lookback).max()
    bars['donchian_low'] = bars.low.shift(1).rolling(
        config.lookback, min_periods=config.lookback).min()
    return bars


def generate_daily_turtle_signals(
    bars: pd.DataFrame,
    config: DailyTurtleConfig,
    symbol: str,
) -> list[dict]:
    records = []
    for row in bars.itertuples():
        local_atr = float(row.atr)
        if not np.isfinite(local_atr) or local_atr <= 0:
            continue
        if not np.isfinite(row.donchian_high) or not np.isfinite(row.donchian_low):
            continue
        side = None
        stop = None
        if row.close > row.donchian_high:
            side = 1
            stop = float(row.close) - config.stop_atr_mult * local_atr
        elif row.close < row.donchian_low:
            side = -1
            stop = float(row.close) + config.stop_atr_mult * local_atr
        if side is None:
            continue
        risk = side * (row.close - stop)
        if risk <= 0:
            continue
        direction = 'long' if side == 1 else 'short'
        records.append({
            'timestamp': row.Index,
            'side': side,
            'reference': float(row.close),
            'stop': float(stop),
            'atr': local_atr,
            'min_stop_atr': 0.5,
            'max_stop_atr': 8.0,
            'score': 7,
            'setup': 'daily_turtle_20',
            'setup_id': (
                f'S64:turtle20:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
