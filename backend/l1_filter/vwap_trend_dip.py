"""S65 H1: VWAP dip-reclaim in 4h trend, hold toward the session close.

Mean reversion inside trend, not a breakout. Distinct from S49/S50 (ORB 1R)
and S64 prior-day breakout. 15m close below session VWAP, then reclaim,
stop under the reclaim bar, 12h hold, $10 risk.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .oi_state_transition_scalp import _confirmed_structure
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class VwapTrendDipConfig:
    name: str = 'S65_vwap_trend_dip'
    pivot_width: int = 2
    stop_atr_mult: float = 0.35
    entry_start_minute: int = 60
    entry_end_minute: int = 12 * 60
    target_r: float = 8.0
    max_hold_minutes: int = 12 * 60

    def __post_init__(self):
        if (self.pivot_width < 1 or self.stop_atr_mult <= 0
                or self.entry_end_minute <= self.entry_start_minute
                or self.target_r < 6 or self.max_hold_minutes < 10 * 60):
            raise ValueError('Invalid S65 VWAP configuration')

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


def vwap_trend_dip_features(
    minutes: pd.DataFrame, config: VwapTrendDipConfig,
) -> pd.DataFrame:
    bars = resample_closed(minutes, 15)
    four_hour = resample_closed(minutes, 240)
    typical = (bars.high + bars.low + bars.close) / 3
    utc = bars.index.tz_convert('UTC')
    session_day = utc.normalize()
    pv = typical * bars.volume
    bars['vwap'] = pv.groupby(session_day).cumsum() / bars.volume.groupby(session_day).cumsum()
    bars['atr'] = talib.ATR(
        bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy(), 14)
    bars['regime'] = _confirmed_structure(
        four_hour, config.pivot_width
    ).reindex(bars.index, method='ffill').fillna(0).astype(int)
    bars['session_day'] = session_day
    clock = utc.hour * 60 + utc.minute
    bars['in_entry_window'] = (
        (clock > config.entry_start_minute) & (clock <= config.entry_end_minute))
    return bars


def generate_vwap_trend_dip_signals(
    bars: pd.DataFrame,
    config: VwapTrendDipConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_days = set()
    prev_close = prev_vwap = prev_day = None
    for row in bars.itertuples():
        day = row.session_day
        close, vwap = float(row.close), float(row.vwap)
        if (day not in used_days and row.in_entry_window
                and prev_day == day and prev_close is not None
                and np.isfinite(vwap) and np.isfinite(prev_vwap)):
            local_atr = float(row.atr)
            regime = int(row.regime)
            if np.isfinite(local_atr) and local_atr > 0 and regime != 0:
                long_reclaim = regime == 1 and prev_close < prev_vwap and close > vwap
                short_reclaim = regime == -1 and prev_close > prev_vwap and close < vwap
                side = 1 if long_reclaim else (-1 if short_reclaim else None)
                if side is not None:
                    stop = close - side * config.stop_atr_mult * local_atr
                    if side * (close - stop) > 0:
                        used_days.add(day)
                        direction = 'long' if side == 1 else 'short'
                        records.append({
                            'timestamp': row.Index,
                            'side': side,
                            'reference': close,
                            'stop': float(stop),
                            'atr': local_atr,
                            'min_stop_atr': 0.15,
                            'max_stop_atr': 8.0,
                            'score': 7,
                            'setup': 'vwap_trend_dip',
                            'setup_id': (
                                f'S65:vwap:{symbol}:{direction}:{row.Index.isoformat()}'
                            ),
                        })
        prev_close, prev_vwap, prev_day = close, vwap, day
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
