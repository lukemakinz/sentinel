"""S52: fade a NY-cash-open sweep of the Asia range.

UTC/London 15-30m ORB failed (S49/S50) because crypto does not have a
pit open at those clocks. US equity cash open (13:00-16:00 UTC) does
create a real flow event: alts often raid the overnight Asia high/low
and snap back. This is not a retune of the 15-minute opening range.

Routes:
  ny_sweep_fade      — fade the first failed Asia-range sweep, any 4h regime
  ny_sweep_sideline  — same, only on 4h SIDELINE days

Asia range: 00:00-12:00 UTC. Sweep window: 13:00-16:00 UTC.
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
class NYAsiaSweepConfig:
    name: str = 'S52_ny_asia_sweep'
    route: str = 'ny_sweep_fade'
    pivot_width: int = 2
    asia_end_hour: int = 12
    sweep_start_hour: int = 13
    sweep_end_hour: int = 16
    min_asia_atr: float = 0.80
    max_asia_atr: float = 6.00
    target_r: float = 1.0
    max_hold_minutes: int = 90

    def __post_init__(self):
        if self.route not in ('ny_sweep_fade', 'ny_sweep_sideline'):
            raise ValueError('Unknown S52 route')
        if (self.pivot_width < 1
                or not 0 < self.asia_end_hour < self.sweep_start_hour < self.sweep_end_hour <= 24
                or self.min_asia_atr <= 0 or self.max_asia_atr <= self.min_asia_atr
                or self.target_r <= 0 or self.max_hold_minutes < 1):
            raise ValueError('Invalid S52 configuration')

    @property
    def sideline_only(self) -> bool:
        return self.route == 'ny_sweep_sideline'

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


def ny_asia_sweep_features(minutes: pd.DataFrame, config: NYAsiaSweepConfig) -> pd.DataFrame:
    bars = resample_closed(minutes, 5)
    hourly = resample_closed(minutes, 60)
    four_hour = resample_closed(minutes, 240)
    hourly_atr = talib.ATR(
        hourly.high.to_numpy(), hourly.low.to_numpy(), hourly.close.to_numpy(), 14
    )
    bars['atr1h'] = pd.Series(hourly_atr, index=hourly.index).reindex(
        bars.index, method='ffill')
    bars['regime'] = _confirmed_structure(
        four_hour, config.pivot_width
    ).reindex(bars.index, method='ffill').fillna(0).astype(int)
    utc = bars.index.tz_convert('UTC')
    bars['session_day'] = utc.normalize()
    clock = utc.hour * 60 + utc.minute
    asia_end = config.asia_end_hour * 60
    in_asia = (clock > 0) & (clock <= asia_end)
    bars['asia_high'] = bars.high.where(in_asia).groupby(bars.session_day).transform('max')
    bars['asia_low'] = bars.low.where(in_asia).groupby(bars.session_day).transform('min')
    bars['sweep_ready'] = clock >= config.sweep_start_hour * 60
    bars['in_sweep_window'] = (
        (utc.hour >= config.sweep_start_hour) & (utc.hour < config.sweep_end_hour)
    )
    width = bars.asia_high - bars.asia_low
    bars['asia_width_ok'] = (
        (width >= config.min_asia_atr * bars.atr1h)
        & (width <= config.max_asia_atr * bars.atr1h)
        & bars.atr1h.gt(0)
    )
    return bars


def generate_ny_asia_sweep_signals(
    bars: pd.DataFrame,
    config: NYAsiaSweepConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_days = set()
    sweep_side = None
    sweep_extreme = None
    current_day = None
    for row in bars.itertuples():
        day = row.session_day
        if day != current_day:
            current_day = day
            sweep_side = None
            sweep_extreme = None
        if day in used_days:
            continue
        if not row.sweep_ready or not row.asia_width_ok:
            continue
        if hasattr(row, 'in_sweep_window') and not row.in_sweep_window:
            continue
        if config.sideline_only and int(row.regime) != 0:
            continue
        local_atr = float(row.atr1h)
        if not np.isfinite(local_atr):
            continue
        if sweep_side is None:
            if row.close > row.asia_high:
                sweep_side = 1
                sweep_extreme = float(row.high)
            elif row.close < row.asia_low:
                sweep_side = -1
                sweep_extreme = float(row.low)
            continue
        if sweep_side == 1 and row.high > sweep_extreme:
            sweep_extreme = float(row.high)
        elif sweep_side == -1 and row.low < sweep_extreme:
            sweep_extreme = float(row.low)
        side = None
        stop = None
        if (sweep_side == 1 and row.close < row.asia_high
                and row.close > row.asia_low):
            side = -1
            stop = sweep_extreme
        elif (sweep_side == -1 and row.close > row.asia_low
                and row.close < row.asia_high):
            side = 1
            stop = sweep_extreme
        if side is None or stop is None:
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
            'setup': f'ny_asia_sweep_{config.route}',
            'setup_id': (
                f'S52:{config.route}:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
