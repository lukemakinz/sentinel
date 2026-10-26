"""S60: taker-flow flush then rebuild, 2.5R.

S47's OI reset→rebuild fired twice in nine months. This is the same
professional idea on a series we already have every minute: aggressive
taker flow dumps, then the book rebuilds in the 4h-trend direction.
Not a retune of S47 OI thresholds.

Routes:
  flow_reset_15m — 15m flush/rebuild, 240-minute hold
  flow_reset_5m  — 5m flush/rebuild, 90-minute hold
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .oi_state_transition_scalp import _confirmed_structure
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class TakerFlowResetConfig:
    name: str = 'S60_taker_flow_reset'
    route: str = 'flow_reset_15m'
    pivot_width: int = 2
    lookback_bars: int = 8
    flush_long_ratio: float = 0.38
    recover_long_ratio: float = 0.55
    flush_short_ratio: float = 0.62
    recover_short_ratio: float = 0.45
    confirmation_expiry_bars: int = 4
    stop_buffer_atr_mult: float = 0.25
    target_r: float = 2.5

    def __post_init__(self):
        if self.route not in ('flow_reset_15m', 'flow_reset_5m'):
            raise ValueError('Unknown S60 route')
        if (self.pivot_width < 1 or self.lookback_bars < 4
                or not 0 < self.flush_long_ratio < self.recover_long_ratio < 1
                or not 0 < self.recover_short_ratio < self.flush_short_ratio < 1
                or self.confirmation_expiry_bars < 1
                or self.stop_buffer_atr_mult < 0 or self.target_r <= 1.0):
            raise ValueError('Invalid S60 configuration')

    @property
    def minutes(self) -> int:
        return 15 if self.route == 'flow_reset_15m' else 5

    @property
    def max_hold_minutes(self) -> int:
        return 240 if self.route == 'flow_reset_15m' else 90

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=self.minutes if self.minutes in (5, 15, 60) else 15,
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


def taker_flow_reset_features(
    minutes: pd.DataFrame,
    config: TakerFlowResetConfig,
) -> pd.DataFrame:
    bars = resample_closed(minutes, config.minutes)
    four_hour = resample_closed(minutes, 240)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['regime'] = _confirmed_structure(
        four_hour, config.pivot_width
    ).reindex(bars.index, method='ffill').fillna(0).astype(int)
    volume = bars.volume.replace(0, np.nan)
    bars['taker_ratio'] = bars.taker_buy_volume / volume
    bars['prior_high'] = bars.high.shift(1).rolling(
        config.lookback_bars, min_periods=config.lookback_bars).max()
    bars['prior_low'] = bars.low.shift(1).rolling(
        config.lookback_bars, min_periods=config.lookback_bars).min()
    bars['bucket'] = bars.index.floor('4h')
    return bars


def generate_taker_flow_reset_signals(
    bars: pd.DataFrame,
    config: TakerFlowResetConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_buckets = set()
    pending = None
    for i, row in enumerate(bars.itertuples()):
        if pending is not None and i > pending['expires']:
            pending = None
        regime = int(row.regime)
        ratio = float(row.taker_ratio) if np.isfinite(row.taker_ratio) else None
        local_atr = float(row.atr)
        if pending is not None and ratio is not None and np.isfinite(local_atr):
            side = pending['side']
            recovered = (
                (side == 1 and ratio >= config.recover_long_ratio
                 and np.isfinite(row.prior_high) and row.close > row.prior_high)
                or (side == -1 and ratio <= config.recover_short_ratio
                    and np.isfinite(row.prior_low) and row.close < row.prior_low)
            )
            if recovered and row.bucket not in used_buckets:
                stop = (
                    float(row.low) - config.stop_buffer_atr_mult * local_atr
                    if side == 1 else
                    float(row.high) + config.stop_buffer_atr_mult * local_atr
                )
                risk = side * (row.close - stop)
                if risk > 0:
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
                        'setup': f'taker_flow_reset_{config.route}',
                        'setup_id': (
                            f'S60:{config.route}:{symbol}:{direction}:'
                            f'{row.Index.isoformat()}'
                        ),
                    })
                    pending = None
                    continue
        if regime not in (-1, 1) or ratio is None:
            continue
        if pending is None:
            if regime == 1 and ratio <= config.flush_long_ratio:
                pending = {'side': 1, 'expires': i + config.confirmation_expiry_bars}
            elif regime == -1 and ratio >= config.flush_short_ratio:
                pending = {'side': -1, 'expires': i + config.confirmation_expiry_bars}
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
