"""S48: one playbook per 4h regime, with early profit-taking.

UP:   only long continuation after a 15m EMA20 pullback.
DOWN: only short continuation after a 15m EMA20 pullback.
SIDELINE: either sit out (route 'trend_only') or fade a failed 15m
          range breakout (route 'regime_switch').

Early profit is the execution itself: 1.0R hard target, 60-minute time
stop, no trailing. S19 already showed that moving the stop to breakeven
and trailing does not rescue the same entries.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .oi_state_transition_scalp import _confirmed_structure
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class RegimePlaybookConfig:
    name: str = 'S48_regime_playbook'
    route: str = 'trend_only'  # or 'regime_switch'
    pivot_width: int = 2
    ema_period: int = 20
    stop_buffer_atr_mult: float = 0.15
    range_lookback_bars: int = 16
    target_r: float = 1.0
    max_hold_minutes: int = 60

    def __post_init__(self):
        if self.route not in ('trend_only', 'regime_switch'):
            raise ValueError('Unknown regime playbook route')
        if (self.pivot_width < 1 or self.ema_period < 2
                or self.stop_buffer_atr_mult < 0
                or self.range_lookback_bars < 4
                or self.target_r <= 0 or self.max_hold_minutes < 1):
            raise ValueError('Invalid S48 configuration')

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


def regime_playbook_features(
    minutes: pd.DataFrame,
    config: RegimePlaybookConfig,
) -> pd.DataFrame:
    bars = resample_closed(minutes, 15)
    four_hour = resample_closed(minutes, 240)
    close = bars.close.to_numpy()
    bars['atr15'] = talib.ATR(
        bars.high.to_numpy(), bars.low.to_numpy(), close, 14)
    bars['ema20'] = talib.EMA(close, timeperiod=config.ema_period)
    bars['regime'] = _confirmed_structure(
        four_hour, config.pivot_width
    ).reindex(bars.index, method='ffill').fillna(0).astype(int)
    lookback = config.range_lookback_bars
    bars['range_high'] = bars.high.shift(1).rolling(lookback, min_periods=lookback).max()
    bars['range_low'] = bars.low.shift(1).rolling(lookback, min_periods=lookback).min()
    return bars


def generate_regime_playbook_signals(
    bars: pd.DataFrame,
    config: RegimePlaybookConfig,
    symbol: str,
) -> list[dict]:
    records = []
    atr = bars.atr15.to_numpy()
    for i, row in enumerate(bars.itertuples()):
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        regime = int(row.regime)
        if regime == 1:
            signal = _continuation(row, side=1, atr=float(atr[i]), config=config)
        elif regime == -1:
            signal = _continuation(row, side=-1, atr=float(atr[i]), config=config)
        elif config.route == 'regime_switch':
            signal = _sideline_fade(row, atr=float(atr[i]), config=config)
        else:
            signal = None
        if signal is None:
            continue
        direction = 'long' if signal['side'] == 1 else 'short'
        records.append({
            **signal,
            'timestamp': row.Index,
            'atr': float(atr[i]),
            'min_stop_atr': 0.4,
            'max_stop_atr': 4.0,
            'score': 4 if signal['setup'].startswith('sideline') else 6,
            'setup_id': (
                f'S48:{config.route}:{symbol}:{direction}:{row.Index.isoformat()}'
            ),
        })
    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]


def _continuation(row, side: int, atr: float, config: RegimePlaybookConfig):
    if not np.isfinite(row.ema20):
        return None
    pulled = (
        row.low <= row.ema20 if side == 1 else row.high >= row.ema20)
    recovered = (
        row.close > row.ema20 if side == 1 else row.close < row.ema20)
    body = side * (row.close - row.open) > 0
    if not (pulled and recovered and body):
        return None
    extreme = float(row.low if side == 1 else row.high)
    stop = extreme - side * config.stop_buffer_atr_mult * atr
    if side * (row.close - stop) <= 0:
        return None
    return {
        'side': side,
        'reference': float(row.close),
        'stop': float(stop),
        'setup': 'trend_continuation',
    }


def _sideline_fade(row, atr: float, config: RegimePlaybookConfig):
    if not (np.isfinite(row.range_high) and np.isfinite(row.range_low)):
        return None
    if row.high > row.range_high and row.close < row.range_high and row.close < row.open:
        side = -1
        extreme = float(row.high)
    elif row.low < row.range_low and row.close > row.range_low and row.close > row.open:
        side = 1
        extreme = float(row.low)
    else:
        return None
    stop = extreme - side * config.stop_buffer_atr_mult * atr
    if side * (row.close - stop) <= 0:
        return None
    return {
        'side': side,
        'reference': float(row.close),
        'stop': float(stop),
        'setup': 'sideline_fade',
    }
