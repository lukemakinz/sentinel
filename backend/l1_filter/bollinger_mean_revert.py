"""S69 H2: 4h Bollinger fade back to the mid band in a quiet ADX regime.

Not S13 (squeeze expansion breakout at $0.50). Close through the 2-sigma
band while 4h ADX < 25 is a fade, target is the mid band, 24h cap,
two slots, $15 risk. One attempt per UTC day per symbol.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class BollingerMeanRevertConfig:
    name: str = 'S69_bb_mean_revert'
    period: int = 20
    deviations: float = 2.0
    adx_max: float = 25.0
    stop_atr_mult: float = 1.0
    max_hold_minutes: int = 1440

    def __post_init__(self):
        if (self.period != 20 or self.deviations != 2.0 or self.adx_max != 25.0
                or self.stop_atr_mult != 1.0 or self.max_hold_minutes != 1440):
            raise ValueError('Invalid S69 Bollinger configuration')

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=8.0,
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


def bollinger_mean_revert_features(
    minutes: pd.DataFrame, config: BollingerMeanRevertConfig,
) -> pd.DataFrame:
    bars = resample_closed(minutes, 240)
    close = bars.close.to_numpy()
    upper, mid, lower = talib.BBANDS(
        close, timeperiod=config.period, nbdevup=config.deviations,
        nbdevdn=config.deviations, matype=0)
    bars['bb_upper'] = upper
    bars['bb_mid'] = mid
    bars['bb_lower'] = lower
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['adx'] = talib.ADX(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['session_day'] = bars.index.tz_convert('UTC').normalize()
    return bars


def generate_bollinger_mean_revert_signals(
    bars: pd.DataFrame,
    config: BollingerMeanRevertConfig,
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
        mid = float(row.bb_mid)
        if not np.isfinite(local_atr) or local_atr <= 0 or not np.isfinite(adx):
            continue
        if adx >= config.adx_max or not np.isfinite(mid):
            continue
        upper, lower = float(row.bb_upper), float(row.bb_lower)
        if not np.isfinite(upper) or not np.isfinite(lower):
            continue
        side = None
        if row.close < lower:
            side = 1
        elif row.close > upper:
            side = -1
        if side is None:
            continue
        stop = float(row.close) - side * config.stop_atr_mult * local_atr
        if side * (row.close - stop) <= 0 or side * (mid - row.close) <= 0:
            continue
        used_days.add(day)
        direction = 'long' if side == 1 else 'short'
        records.append({
            'timestamp': row.Index,
            'side': side,
            'reference': float(row.close),
            'stop': float(stop),
            'target_price': mid,
            'atr': local_atr,
            'min_stop_atr': 0.5,
            'max_stop_atr': 8.0,
            'score': 7,
            'setup': 'bb_mean_revert',
            'setup_id': f'S69:bb:{symbol}:{direction}:{row.Index.isoformat()}',
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
