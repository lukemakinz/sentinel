"""S67 H2: 1h Donchian-10 breakout gated by ADX, uncapped 24h hold.

Not S55 (4h channel, 2.5R, one slot, $0.50) and not S64 daily turtle.
Hourly close through the prior 10-hour channel only if ADX>=25,
1.0 ATR stop, 8R cap so TIME/STOP dominate, two slots, $15 risk.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class HourlyDonchianAdxConfig:
    name: str = 'S67_hourly_donchian_adx'
    lookback: int = 10
    adx_min: float = 25.0
    stop_atr_mult: float = 1.00
    target_r: float = 8.0
    max_hold_minutes: int = 1440

    def __post_init__(self):
        if (self.lookback != 10 or self.adx_min != 25.0
                or self.stop_atr_mult <= 0 or self.target_r < 8
                or self.max_hold_minutes != 1440):
            raise ValueError('Invalid S67 hourly Donchian configuration')

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
            risk_fraction=0.06,
            max_notional_equity=4.0,
            daily_loss_fraction=0.14,
            weekly_loss_fraction=0.22,
            drawdown_halt_fraction=0.28,
            drawdown_risk_scale_fraction=0.16,
            max_positions=2,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=0.5,
            leverage=5.0,
            max_margin_fraction=0.25,
            margin_safety_reserve=0.01,
            maker_fee_bps=5.0,
            limit_penetration_bps=0.0,
            fixed_margin_usd=None,
            fixed_risk_usd=15.0,
        )


def hourly_donchian_adx_features(
    minutes: pd.DataFrame, config: HourlyDonchianAdxConfig,
) -> pd.DataFrame:
    bars = resample_closed(minutes, 60)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['adx'] = talib.ADX(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['donchian_high'] = bars.high.shift(1).rolling(
        config.lookback, min_periods=config.lookback).max()
    bars['donchian_low'] = bars.low.shift(1).rolling(
        config.lookback, min_periods=config.lookback).min()
    bars['session_day'] = bars.index.tz_convert('UTC').normalize()
    return bars


def generate_hourly_donchian_adx_signals(
    bars: pd.DataFrame,
    config: HourlyDonchianAdxConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_days = set()
    for row in bars.itertuples():
        day = row.session_day
        if day in used_days:
            continue
        local_atr = float(row.atr)
        adx = float(row.adx)
        if not np.isfinite(local_atr) or local_atr <= 0 or not np.isfinite(adx):
            continue
        if adx < config.adx_min:
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
        if side is None or side * (row.close - stop) <= 0:
            continue
        used_days.add(day)
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
            'setup': 'hourly_donchian_adx',
            'setup_id': (
                f'S67:hdonch:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
