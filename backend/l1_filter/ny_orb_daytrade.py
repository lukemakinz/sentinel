"""S67 H1: NY cash-open range breakout, hold toward the UTC evening.

Not S49 (00:00/07:00 1R 90m scalp) and not S64 prior-day breakout.
13:00-14:00 UTC range, first 5m close through it with daily SMA20 trend,
stop the other side of the range, 5h hold, two symbol slots, $15 risk.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class NyOrbConfig:
    name: str = 'S67_ny_orb_htc'
    session_hour: int = 13
    range_minutes: int = 60
    entry_until_hour: int = 17
    min_or_atr: float = 0.20
    max_or_atr: float = 2.00
    target_r: float = 8.0
    max_hold_minutes: int = 5 * 60

    def __post_init__(self):
        if (self.session_hour != 13 or self.range_minutes != 60
                or self.entry_until_hour <= self.session_hour
                or self.max_or_atr <= self.min_or_atr
                or self.target_r < 6 or self.max_hold_minutes < 4 * 60):
            raise ValueError('Invalid S67 NY ORB configuration')

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


def ny_orb_features(minutes: pd.DataFrame, config: NyOrbConfig) -> pd.DataFrame:
    bars = resample_closed(minutes, 5)
    hourly = resample_closed(minutes, 60)
    daily = resample_closed(minutes, 1440)
    hourly_atr = talib.ATR(
        hourly.high.to_numpy(), hourly.low.to_numpy(), hourly.close.to_numpy(), 14)
    daily['sma20'] = talib.SMA(daily.close.to_numpy(), 20)
    completed = daily[['close', 'sma20']].copy()
    completed.index = completed.index.normalize()
    completed = completed.rename(columns={'close': 'daily_close'})
    utc = bars.index.tz_convert('UTC')
    bars['session_day'] = utc.normalize()
    bars = bars.join(completed, on='session_day')
    bars['atr'] = pd.Series(hourly_atr, index=hourly.index).reindex(
        bars.index, method='ffill')
    range_end = config.session_hour * 60 + config.range_minutes
    clock = utc.hour * 60 + utc.minute
    in_range = (clock > config.session_hour * 60) & (clock <= range_end)
    bars['or_high'] = bars.high.where(in_range).groupby(bars.session_day).transform('max')
    bars['or_low'] = bars.low.where(in_range).groupby(bars.session_day).transform('min')
    bars['or_ready'] = clock > range_end
    bars['in_entry_window'] = (clock > range_end) & (utc.hour < config.entry_until_hour)
    width = bars.or_high - bars.or_low
    bars['or_width_ok'] = (
        (width >= config.min_or_atr * bars.atr)
        & (width <= config.max_or_atr * bars.atr)
        & bars.atr.gt(0)
    )
    return bars


def generate_ny_orb_signals(
    bars: pd.DataFrame,
    config: NyOrbConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_days = set()
    for row in bars.itertuples():
        day = row.session_day
        if day in used_days or not row.or_ready or not row.or_width_ok:
            continue
        if not row.in_entry_window:
            continue
        local_atr = float(row.atr)
        sma = float(row.sma20)
        daily_close = float(row.daily_close)
        if not np.isfinite(local_atr) or local_atr <= 0:
            continue
        if not np.isfinite(sma) or not np.isfinite(daily_close):
            continue
        side = None
        stop = None
        if daily_close > sma and row.close > row.or_high:
            side = 1
            stop = float(row.or_low)
        elif daily_close < sma and row.close < row.or_low:
            side = -1
            stop = float(row.or_high)
        if side is None:
            continue
        if side * (row.close - stop) <= 0:
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
            'setup': 'ny_orb_htc',
            'setup_id': f'S67:nyorb:{symbol}:{direction}:{row.Index.isoformat()}',
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
