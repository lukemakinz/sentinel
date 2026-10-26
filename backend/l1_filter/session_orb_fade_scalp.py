"""S50: fade a failed clock-session opening-range break.

S49 showed with-trend ORB breaks lose after costs (UTC PF 0.35, London 0.64).
The complementary professional play: wait for the first close outside the
opening range; if price reclaims the range on a later bar, fade back toward
the opposite side. One attempt per day. Not a retune of S49.

Routes:
  utc_failed_fade       — 00:00-00:15 UTC range, fade in any 4h regime
  london_sideline_fade  — 07:00-07:30 UTC range, fade only on SIDELINE days
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .scalp_strategy import ScalpConfig
from .session_orb_scalp import SessionORBConfig, session_orb_features


@dataclass(frozen=True)
class SessionORBFadeConfig:
    name: str = 'S50_session_orb_fade'
    route: str = 'utc_failed_fade'
    pivot_width: int = 2
    min_or_atr: float = 0.25
    max_or_atr: float = 1.80
    target_r: float = 1.0
    max_hold_minutes: int = 90

    def __post_init__(self):
        if self.route not in ('utc_failed_fade', 'london_sideline_fade'):
            raise ValueError('Unknown S50 route')
        if (self.pivot_width < 1 or self.min_or_atr <= 0
                or self.max_or_atr <= self.min_or_atr
                or self.target_r <= 0 or self.max_hold_minutes < 1):
            raise ValueError('Invalid S50 configuration')

    @property
    def sideline_only(self) -> bool:
        return self.route == 'london_sideline_fade'

    def orb_config(self) -> SessionORBConfig:
        orb_route = (
            'utc_open_with_trend' if self.route.startswith('utc')
            else 'london_with_trend'
        )
        return SessionORBConfig(
            name=self.name,
            route=orb_route,
            pivot_width=self.pivot_width,
            min_or_atr=self.min_or_atr,
            max_or_atr=self.max_or_atr,
            target_r=self.target_r,
            max_hold_minutes=self.max_hold_minutes,
        )

    def execution(self) -> ScalpConfig:
        return self.orb_config().execution()


def session_orb_fade_features(minutes, config: SessionORBFadeConfig):
    return session_orb_features(minutes, config.orb_config())


def generate_session_orb_fade_signals(
    bars,
    config: SessionORBFadeConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_days = set()
    break_side = None
    break_extreme = None
    current_day = None
    for row in bars.itertuples():
        day = row.session_day
        if day != current_day:
            current_day = day
            break_side = None
            break_extreme = None
        if day in used_days:
            continue
        if not row.or_ready or not row.or_width_ok:
            continue
        if hasattr(row, 'in_trade_window') and not row.in_trade_window:
            continue
        if config.sideline_only and int(row.regime) != 0:
            continue
        local_atr = float(row.atr1h)
        if not np.isfinite(local_atr):
            continue
        if break_side is None:
            if row.close > row.or_high:
                break_side = 1
                break_extreme = float(row.high)
            elif row.close < row.or_low:
                break_side = -1
                break_extreme = float(row.low)
            continue
        if break_side == 1 and row.high > break_extreme:
            break_extreme = float(row.high)
        elif break_side == -1 and row.low < break_extreme:
            break_extreme = float(row.low)
        side = None
        stop = None
        if break_side == 1 and row.close < row.or_high and row.close > row.or_low:
            side = -1
            stop = break_extreme
        elif break_side == -1 and row.close > row.or_low and row.close < row.or_high:
            side = 1
            stop = break_extreme
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
            'setup': f'session_orb_fade_{config.route}',
            'setup_id': (
                f'S50:{config.route}:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
