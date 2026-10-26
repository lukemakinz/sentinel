"""S64 H2: prior-day high/low breakout, hold toward the UTC close.

Not S49 (15-30m opening range, 1R, 90-minute scalp) and not S55 (4h Donchian 2.5R).
First 5m close through yesterday's high/low in the 01:00-06:00 UTC window,
0.5 prior-day-range stop, 4h trend filter, ~16h hold, $10 risk.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .oi_state_transition_scalp import _confirmed_structure
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class PriorDayBreakoutConfig:
    name: str = 'S64_prior_day_htc'
    pivot_width: int = 2
    stop_range_fraction: float = 0.50
    min_range_atr: float = 0.25
    max_range_atr: float = 2.50
    entry_start_minute: int = 60
    entry_end_minute: int = 360
    target_r: float = 8.0
    max_hold_minutes: int = 16 * 60

    def __post_init__(self):
        if (self.pivot_width < 1 or not 0 < self.stop_range_fraction < 1
                or self.max_range_atr <= self.min_range_atr
                or self.entry_end_minute <= self.entry_start_minute
                or self.target_r < 6 or self.max_hold_minutes < 12 * 60):
            raise ValueError('Invalid S64 prior-day configuration')

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


def prior_day_breakout_features(
    minutes: pd.DataFrame, config: PriorDayBreakoutConfig,
) -> pd.DataFrame:
    bars = resample_closed(minutes, 5)
    daily = resample_closed(minutes, 1440)
    four_hour = resample_closed(minutes, 240)
    daily_atr = talib.ATR(
        daily.high.to_numpy(), daily.low.to_numpy(), daily.close.to_numpy(), 14)
    daily['atr'] = daily_atr
    completed = daily[['high', 'low', 'atr']].copy()
    completed.index = completed.index.normalize()
    completed = completed.rename(columns={'high': 'prev_high', 'low': 'prev_low'})
    completed['prev_range'] = completed.prev_high - completed.prev_low
    utc = bars.index.tz_convert('UTC')
    bars['session_day'] = utc.normalize()
    bars = bars.join(completed, on='session_day')
    bars['regime'] = _confirmed_structure(
        four_hour, config.pivot_width
    ).reindex(bars.index, method='ffill').fillna(0).astype(int)
    clock = utc.hour * 60 + utc.minute
    bars['in_entry_window'] = (
        (clock > config.entry_start_minute) & (clock <= config.entry_end_minute))
    return bars


def generate_prior_day_breakout_signals(
    bars: pd.DataFrame,
    config: PriorDayBreakoutConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_days = set()
    for row in bars.itertuples():
        day = row.session_day
        if day in used_days or not row.in_entry_window:
            continue
        regime = int(row.regime)
        if regime == 0:
            continue
        local_atr = float(row.atr)
        prev_range = float(row.prev_range)
        if (not np.isfinite(local_atr) or local_atr <= 0
                or not np.isfinite(prev_range) or prev_range <= 0):
            continue
        if not (config.min_range_atr * local_atr
                <= prev_range
                <= config.max_range_atr * local_atr):
            continue
        side = None
        if regime == 1 and row.close > row.prev_high:
            side = 1
        elif regime == -1 and row.close < row.prev_low:
            side = -1
        if side is None:
            continue
        stop = float(row.close) - side * config.stop_range_fraction * prev_range
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
            'setup': 'prior_day_htc',
            'setup_id': (
                f'S64:priorday:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
