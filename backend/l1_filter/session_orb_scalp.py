"""S49: clock-session opening-range breakout.

This is not D1's rolling 1-hour high/low. A professional day-trader
fixes the range at a session open, takes at most one close through that
range, and is done for the day.

Routes:
  utc_open_with_trend  — 00:00-00:15 UTC range; only with 4h UP/DOWN
  london_with_trend    — 07:00-07:30 UTC range; only with 4h UP/DOWN

SIDELINE days are skipped. Early profit: 1.0R, 90-minute time stop, no trail.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .oi_state_transition_scalp import _confirmed_structure
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class SessionORBConfig:
    name: str = 'S49_session_orb'
    route: str = 'utc_open_with_trend'
    pivot_width: int = 2
    min_or_atr: float = 0.25
    max_or_atr: float = 1.80
    volume_mult: float = 1.2
    target_r: float = 1.0
    max_hold_minutes: int = 90

    def __post_init__(self):
        if self.route not in ('utc_open_with_trend', 'london_with_trend'):
            raise ValueError('Unknown S49 route')
        if (self.pivot_width < 1 or self.min_or_atr <= 0
                or self.max_or_atr <= self.min_or_atr or self.volume_mult <= 0
                or self.target_r <= 0 or self.max_hold_minutes < 1):
            raise ValueError('Invalid S49 configuration')

    @property
    def session_hour(self) -> int:
        return 0 if self.route.startswith('utc_open') else 7

    @property
    def range_minutes(self) -> int:
        return 15 if self.route.startswith('utc_open') else 30

    @property
    def trade_until_hour(self) -> int:
        return 4 if self.route.startswith('utc_open') else 11

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=5,
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


def session_orb_features(minutes: pd.DataFrame, config: SessionORBConfig) -> pd.DataFrame:
    bars = resample_closed(minutes, 5)
    hourly = resample_closed(minutes, 60)
    four_hour = resample_closed(minutes, 240)
    hourly_atr = talib.ATR(
        hourly.high.to_numpy(), hourly.low.to_numpy(), hourly.close.to_numpy(), 14
    )
    bars['atr1h'] = pd.Series(hourly_atr, index=hourly.index).reindex(
        bars.index, method='ffill'
    )
    bars['regime'] = _confirmed_structure(
        four_hour, config.pivot_width
    ).reindex(bars.index, method='ffill').fillna(0).astype(int)

    utc = bars.index.tz_convert('UTC')
    bars['session_day'] = utc.normalize()
    range_end = config.session_hour * 60 + config.range_minutes
    clock = utc.hour * 60 + utc.minute
    # 5m bars are right-labeled: 00:00-00:15 range is the 00:05, 00:10, 00:15 bars.
    in_range = (clock > config.session_hour * 60) & (clock <= range_end)
    bars['or_high'] = bars.high.where(in_range).groupby(bars.session_day).transform('max')
    bars['or_low'] = bars.low.where(in_range).groupby(bars.session_day).transform('min')
    bars['or_volume'] = bars.volume.where(in_range).groupby(bars.session_day).transform('mean')
    bars['or_ready'] = clock > range_end
    bars['in_trade_window'] = (clock > range_end) & (utc.hour < config.trade_until_hour)
    width = bars.or_high - bars.or_low
    bars['or_width_ok'] = (
        (width >= config.min_or_atr * bars.atr1h)
        & (width <= config.max_or_atr * bars.atr1h)
        & bars.atr1h.gt(0)
    )
    return bars


def generate_session_orb_signals(
    bars: pd.DataFrame,
    config: SessionORBConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_days = set()
    for row in bars.itertuples():
        day = row.session_day
        if day in used_days:
            continue
        if not row.or_ready or not row.or_width_ok:
            continue
        if hasattr(row, 'in_trade_window') and not row.in_trade_window:
            continue
        regime = int(row.regime)
        if regime == 0:
            continue
        local_atr = float(row.atr1h)
        if not np.isfinite(local_atr):
            continue
        or_volume = getattr(row, 'or_volume', None)
        if or_volume is not None and np.isfinite(float(or_volume)):
            if row.volume < config.volume_mult * float(or_volume):
                continue
        side = None
        if regime == 1 and row.close > row.or_high:
            side = 1
            stop = float(row.or_low)
        elif regime == -1 and row.close < row.or_low:
            side = -1
            stop = float(row.or_high)
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
            'setup': f'session_orb_{config.route}',
            'setup_id': f'S49:{config.route}:{symbol}:{direction}:{row.Index.isoformat()}',
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
