"""S65 H2: Connors-style RSI(2) mean reversion on daily bars.

Not S40/S57 (4h RSI 20/80 extremes, rare) and not S64 turtle (breakout).
RSI2 < 10 above SMA20 -> long; RSI2 > 90 below SMA20 -> short.
1.5 ATR stop, 3R or 5-day hold, $10 risk.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class Rsi2Config:
    name: str = 'S65_rsi2'
    rsi_period: int = 2
    oversold: float = 10.0
    overbought: float = 90.0
    sma_period: int = 20
    stop_atr_mult: float = 1.50
    target_r: float = 3.0
    max_hold_days: int = 5

    def __post_init__(self):
        if (self.rsi_period != 2 or not 0 < self.oversold < 50
                or not 50 < self.overbought < 100
                or self.sma_period < 10 or self.stop_atr_mult <= 0
                or self.target_r != 3.0 or self.max_hold_days != 5):
            raise ValueError('Invalid S65 RSI2 configuration')

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


def rsi2_features(minutes: pd.DataFrame, config: Rsi2Config) -> pd.DataFrame:
    bars = resample_closed(minutes, 1440)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['rsi2'] = talib.RSI(close, config.rsi_period)
    bars['sma20'] = talib.SMA(close, config.sma_period)
    return bars


def generate_rsi2_signals(
    bars: pd.DataFrame,
    config: Rsi2Config,
    symbol: str,
) -> list[dict]:
    records = []
    for row in bars.itertuples():
        local_atr = float(row.atr)
        rsi2 = float(row.rsi2)
        sma = float(row.sma20)
        if not np.isfinite(local_atr) or local_atr <= 0:
            continue
        if not np.isfinite(rsi2) or not np.isfinite(sma):
            continue
        side = None
        if rsi2 < config.oversold and row.close > sma:
            side = 1
        elif rsi2 > config.overbought and row.close < sma:
            side = -1
        if side is None:
            continue
        stop = float(row.close) - side * config.stop_atr_mult * local_atr
        if side * (row.close - stop) <= 0:
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
            'setup': 'rsi2_mr',
            'setup_id': (
                f'S65:rsi2:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
