"""S58: daily time-series momentum, 2.5R, multi-day hold.

Classic futures TSMOM, not a 4h Donchian channel (S55) and not a 1R scalp.
Close above the close N days ago -> long; below -> short. ATR stop.
One signal per UTC day per symbol.

Routes:
  tsmom_20 — 20-day lookback, 5-day hold
  tsmom_10 — 10-day lookback, 3-day hold
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class DailyTSMOMConfig:
    name: str = 'S58_daily_tsmom'
    route: str = 'tsmom_20'
    stop_atr_mult: float = 1.50
    target_r: float = 2.5

    def __post_init__(self):
        if self.route not in ('tsmom_20', 'tsmom_10'):
            raise ValueError('Unknown S58 route')
        if self.stop_atr_mult <= 0 or self.target_r <= 1.0:
            raise ValueError('Invalid S58 configuration')

    @property
    def lookback(self) -> int:
        return 20 if self.route == 'tsmom_20' else 10

    @property
    def max_hold_minutes(self) -> int:
        return 7200 if self.route == 'tsmom_20' else 4320

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


def daily_tsmom_features(minutes: pd.DataFrame, config: DailyTSMOMConfig) -> pd.DataFrame:
    bars = resample_closed(minutes, 1440)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['mom'] = bars.close.pct_change(config.lookback)
    return bars


def generate_daily_tsmom_signals(
    bars: pd.DataFrame,
    config: DailyTSMOMConfig,
    symbol: str,
) -> list[dict]:
    records = []
    for row in bars.itertuples():
        mom = float(row.mom) if np.isfinite(row.mom) else 0.0
        if mom == 0:
            continue
        local_atr = float(row.atr)
        if not np.isfinite(local_atr) or local_atr <= 0:
            continue
        if mom > 0:
            side = 1
            stop = float(row.close) - config.stop_atr_mult * local_atr
        else:
            side = -1
            stop = float(row.close) + config.stop_atr_mult * local_atr
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
            'score': min(10, max(1, int(abs(mom) * 400))),
            'setup': f'daily_tsmom_{config.route}',
            'setup_id': (
                f'S58:{config.route}:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
