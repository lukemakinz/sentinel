"""S51: fade a crowded funding squeeze.

Crypto-native desk play, not a session-range retune. When the last known
funding print is in the extreme tail of its 14-day (42-settlement) history,
the book is paying to stay in a crowded trade. Fade on the next 15m
rejection candle, one attempt per settlement.

Routes:
  crowded_fade           — fade extreme funding in any 4h regime
  crowded_fade_sideline  — same, but only when 4h is SIDELINE

Early profit: 1.0R, 120-minute time stop, no trail.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .oi_state_transition_scalp import _confirmed_structure
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class FundingSqueezeConfig:
    name: str = 'S51_funding_squeeze'
    route: str = 'crowded_fade'
    pivot_width: int = 2
    funding_lookback_settlements: int = 42
    extreme_quantile: float = 0.90
    min_abs_funding: float = 0.00005
    stop_buffer_atr_mult: float = 0.15
    target_r: float = 1.0
    max_hold_minutes: int = 120

    def __post_init__(self):
        if self.route not in ('crowded_fade', 'crowded_fade_sideline'):
            raise ValueError('Unknown S51 route')
        if (self.pivot_width < 1 or self.funding_lookback_settlements < 10
                or not 0.5 < self.extreme_quantile < 1
                or self.min_abs_funding <= 0 or self.stop_buffer_atr_mult < 0
                or self.target_r <= 0 or self.max_hold_minutes < 1):
            raise ValueError('Invalid S51 configuration')

    @property
    def sideline_only(self) -> bool:
        return self.route == 'crowded_fade_sideline'

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


def _known_before(series: pd.Series, bars_index: pd.DatetimeIndex) -> pd.Series:
    probe = bars_index - pd.Timedelta(milliseconds=1)
    aligned = series.reindex(probe, method='ffill')
    aligned.index = bars_index
    return aligned


def funding_squeeze_features(
    minutes: pd.DataFrame,
    funding: pd.Series,
    config: FundingSqueezeConfig,
) -> pd.DataFrame:
    bars = resample_closed(minutes, 15)
    four_hour = resample_closed(minutes, 240)
    close = bars.close.to_numpy()
    bars['atr15'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['regime'] = _confirmed_structure(
        four_hour, config.pivot_width
    ).reindex(bars.index, method='ffill').fillna(0).astype(int)
    rates = funding.sort_index().astype(float)
    lookback = config.funding_lookback_settlements
    q_hi = rates.rolling(lookback, min_periods=lookback).quantile(config.extreme_quantile)
    q_lo = rates.rolling(lookback, min_periods=lookback).quantile(
        1.0 - config.extreme_quantile)
    bars['funding'] = _known_before(rates, bars.index)
    bars['funding_q90'] = _known_before(q_hi, bars.index)
    bars['funding_q10'] = _known_before(q_lo, bars.index)
    settlement_times = pd.Series(rates.index, index=rates.index)
    bars['funding_time'] = _known_before(settlement_times, bars.index)
    return bars


def generate_funding_squeeze_signals(
    bars: pd.DataFrame,
    config: FundingSqueezeConfig,
    symbol: str,
) -> list[dict]:
    records = []
    used_settlements = set()
    for row in bars.itertuples():
        funding = float(row.funding) if np.isfinite(row.funding) else None
        if funding is None:
            continue
        if abs(funding) < config.min_abs_funding:
            continue
        if config.sideline_only and int(row.regime) != 0:
            continue
        local_atr = float(row.atr15)
        if not np.isfinite(local_atr) or local_atr <= 0:
            continue
        q90 = float(row.funding_q90)
        q10 = float(row.funding_q10)
        if not np.isfinite(q90) or not np.isfinite(q10):
            continue
        settlement = row.funding_time
        if settlement in used_settlements:
            continue
        side = None
        stop = None
        if funding >= q90 and funding > 0 and row.close < row.open:
            side = -1
            stop = float(row.high) + config.stop_buffer_atr_mult * local_atr
        elif funding <= q10 and funding < 0 and row.close > row.open:
            side = 1
            stop = float(row.low) - config.stop_buffer_atr_mult * local_atr
        if side is None:
            continue
        risk = side * (row.close - stop)
        if risk <= 0:
            continue
        used_settlements.add(settlement)
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
            'setup': f'funding_squeeze_{config.route}',
            'setup_id': (
                f'S51:{config.route}:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
