"""S56: collect crowded funding through the next settlement.

S51 faded extreme funding on a 15m rejection and lost. The desk trade is
the other side of the same print: if longs are paying, be short into the
settlement and harvest the payment. 2.5R, no trail.

Routes:
  carry_through_settlement — enter 1h before 00/08/16 UTC, hold 2h
  carry_and_revert         — same entry, hold 8h for funding + snapback
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .funding_squeeze_scalp import _known_before
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class FundingCarryConfig:
    name: str = 'S56_funding_carry'
    route: str = 'carry_through_settlement'
    funding_lookback_settlements: int = 42
    extreme_quantile: float = 0.90
    min_abs_funding: float = 0.00005
    stop_buffer_atr_mult: float = 0.80
    target_r: float = 2.5

    def __post_init__(self):
        if self.route not in ('carry_through_settlement', 'carry_and_revert'):
            raise ValueError('Unknown S56 route')
        if (self.funding_lookback_settlements < 10
                or not 0.5 < self.extreme_quantile < 1
                or self.min_abs_funding <= 0 or self.stop_buffer_atr_mult <= 0
                or self.target_r <= 1.0):
            raise ValueError('Invalid S56 configuration')

    @property
    def max_hold_minutes(self) -> int:
        return 120 if self.route == 'carry_through_settlement' else 480

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=60,
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


def funding_carry_features(
    minutes: pd.DataFrame,
    funding: pd.Series,
    config: FundingCarryConfig,
) -> pd.DataFrame:
    bars = resample_closed(minutes, 60)
    close = bars.close.to_numpy()
    bars['atr1h'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    rates = funding.sort_index().astype(float)
    lookback = config.funding_lookback_settlements
    q_hi = rates.rolling(lookback, min_periods=lookback).quantile(config.extreme_quantile)
    q_lo = rates.rolling(lookback, min_periods=lookback).quantile(
        1.0 - config.extreme_quantile)
    bars['funding'] = _known_before(rates, bars.index)
    bars['funding_q90'] = _known_before(q_hi, bars.index)
    bars['funding_q10'] = _known_before(q_lo, bars.index)
    utc = bars.index.tz_convert('UTC')
    bars['pre_settlement'] = utc.hour.isin((7, 15, 23)) & (utc.minute == 0)
    return bars


def generate_funding_carry_signals(
    bars: pd.DataFrame,
    config: FundingCarryConfig,
    symbol: str,
) -> list[dict]:
    records = []
    for row in bars.itertuples():
        if not row.pre_settlement:
            continue
        funding = float(row.funding) if np.isfinite(row.funding) else None
        if funding is None or abs(funding) < config.min_abs_funding:
            continue
        q90 = float(row.funding_q90)
        q10 = float(row.funding_q10)
        if not np.isfinite(q90) or not np.isfinite(q10):
            continue
        local_atr = float(row.atr1h)
        if not np.isfinite(local_atr) or local_atr <= 0:
            continue
        side = None
        stop = None
        if funding >= q90 and funding > 0:
            side = -1
            stop = float(row.high) + config.stop_buffer_atr_mult * local_atr
        elif funding <= q10 and funding < 0:
            side = 1
            stop = float(row.low) - config.stop_buffer_atr_mult * local_atr
        if side is None:
            continue
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
            'min_stop_atr': 0.3,
            'max_stop_atr': 8.0,
            'score': 8,
            'setup': f'funding_carry_{config.route}',
            'setup_id': (
                f'S56:{config.route}:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]
