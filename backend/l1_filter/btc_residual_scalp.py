"""S54: fade an alt's 1-hour residual versus BTC.

Desk relative-value, not another session-range fade. When SOL/XRP has
outrun (or lagged) BTC over the last hour by a 48h z-score extreme, fade
the idiosyncratic move. BTC is a lead, never traded. One attempt per 4h.

Routes:
  residual_fade           — fade |z|>=2 in any 4h regime
  residual_fade_sideline  — same, only on SIDELINE days

Early profit: 1.0R, 90-minute time stop, no trail.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .oi_state_transition_scalp import _confirmed_structure
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class BTCResidualConfig:
    name: str = 'S54_btc_residual'
    route: str = 'residual_fade'
    pivot_width: int = 2
    return_bars: int = 4
    z_lookback_bars: int = 192
    z_threshold: float = 2.0
    stop_buffer_atr_mult: float = 0.15
    target_r: float = 1.0
    max_hold_minutes: int = 90

    def __post_init__(self):
        if self.route not in ('residual_fade', 'residual_fade_sideline'):
            raise ValueError('Unknown S54 route')
        if (self.pivot_width < 1 or self.return_bars < 1
                or self.z_lookback_bars < 20 or self.z_threshold <= 0
                or self.stop_buffer_atr_mult < 0 or self.target_r <= 0
                or self.max_hold_minutes < 1):
            raise ValueError('Invalid S54 configuration')

    @property
    def sideline_only(self) -> bool:
        return self.route == 'residual_fade_sideline'

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
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


def btc_residual_features(
    minutes: pd.DataFrame,
    btc_minutes: pd.DataFrame,
    config: BTCResidualConfig,
) -> pd.DataFrame:
    bars = resample_closed(minutes, 15)
    btc = resample_closed(btc_minutes, 15)
    four_hour = resample_closed(minutes, 240)
    close = bars.close.to_numpy()
    bars['atr15'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['regime'] = _confirmed_structure(
        four_hour, config.pivot_width
    ).reindex(bars.index, method='ffill').fillna(0).astype(int)
    bars['btc_close'] = btc.close.reindex(bars.index)
    bars['ret_1h'] = bars.close.pct_change(config.return_bars)
    bars['btc_ret_1h'] = bars.btc_close.pct_change(config.return_bars)
    bars['residual'] = bars.ret_1h - bars.btc_ret_1h
    mean = bars.residual.rolling(config.z_lookback_bars, min_periods=config.z_lookback_bars).mean()
    std = bars.residual.rolling(config.z_lookback_bars, min_periods=config.z_lookback_bars).std()
    bars['residual_z'] = (bars.residual - mean) / std.where(std > 0)
    bars['bucket'] = bars.index.floor('4h')
    return bars


def generate_btc_residual_signals(
    bars: pd.DataFrame,
    config: BTCResidualConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_buckets = set()
    for row in bars.itertuples():
        if row.bucket in used_buckets:
            continue
        if config.sideline_only and int(row.regime) != 0:
            continue
        z = float(row.residual_z)
        if not np.isfinite(z):
            continue
        local_atr = float(row.atr15)
        if not np.isfinite(local_atr) or local_atr <= 0:
            continue
        side = None
        stop = None
        if z >= config.z_threshold and row.close < row.open:
            side = -1
            stop = float(row.high) + config.stop_buffer_atr_mult * local_atr
        elif z <= -config.z_threshold and row.close > row.open:
            side = 1
            stop = float(row.low) - config.stop_buffer_atr_mult * local_atr
        if side is None:
            continue
        risk = side * (row.close - stop)
        if risk <= 0:
            continue
        used_buckets.add(row.bucket)
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
            'setup': f'btc_residual_{config.route}',
            'setup_id': (
                f'S54:{config.route}:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
