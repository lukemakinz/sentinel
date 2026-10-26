"""S7 research strategy. Pure, causal signals; no live orders or DB access.

Index is the candle OPEN time; each signal is indexed by its availability time
(close of the last input candle). Volume profile is an explicitly approximate
histogram of 1m typical prices, not a tick-level volume-at-price reconstruction.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib


@dataclass(frozen=True)
class ScalpConfig:
    name: str = 'S7_reclaim_5m_3of5'
    minutes: int = 5
    mode: str = 'reclaim'  # reclaim, hybrid, momentum (no-profile control)
    min_score: int = 3
    profile: str = 'previous_day'  # or rolling_6h, refreshed each closed hour
    require_divergence: bool = True
    target_r: float = 2.0
    partial_r: float = 1.5
    partial_fraction: float = 0.4
    trail_atr: float = 1.5
    max_hold_minutes: int = 90
    risk_fraction: float = 0.0025
    max_notional_equity: float = 1.0
    daily_loss_fraction: float = 0.015
    fee_bps: float = 5.0
    slippage_bps: float = 2.0  # adverse fill, each side; includes spread allowance
    min_reward_cost_ratio: float = 3.0
    trailing: bool = True
    leverage: float = 1.0
    max_margin_fraction: float = 1.0
    margin_safety_reserve: float = 0.01
    maker_fee_bps: float = 2.0
    limit_penetration_bps: float = 2.0
    fixed_margin_usd: float | None = None
    fixed_risk_usd: float | None = None
    consecutive_loss_halt: int = 0
    consecutive_loss_halt_side: str = 'all'
    dollar_ratchet: bool = False
    dollar_ratchet_lock_fraction: float = 0.5
    weekly_loss_fraction: float = 0.018
    drawdown_halt_fraction: float = 0.06
    drawdown_risk_scale_fraction: float = 0.04
    max_positions: int = 1
    flip_on_opposite_signal: bool = False

    def __post_init__(self):
        if self.minutes not in (5, 15, 60) or self.mode not in ('reclaim', 'hybrid', 'momentum'):
            raise ValueError('Unsupported timeframe or setup mode')
        if self.profile not in ('previous_day', 'rolling_6h') or not 1 <= self.min_score <= 5:
            raise ValueError('Invalid profile or score')
        if not (0 < self.risk_fraction < 1 and 0 < self.daily_loss_fraction < 1
                and self.max_notional_equity > 0 and self.max_hold_minutes > 0
                and self.target_r > self.partial_r > 0 and 0 <= self.partial_fraction < 1
                and self.fee_bps >= 0 and self.slippage_bps >= 0
                and self.trail_atr > 0 and self.min_reward_cost_ratio >= 0
                and 1 <= self.leverage <= 30 and 0 < self.max_margin_fraction <= 1
                and 0 <= self.margin_safety_reserve < 1 / self.leverage
                and self.maker_fee_bps >= 0 and self.limit_penetration_bps >= 0):
            raise ValueError('Invalid risk or execution parameters')
        if any(x is not None and x <= 0 for x in (self.fixed_margin_usd, self.fixed_risk_usd)):
            raise ValueError('Fixed margin and risk must be positive')
        if self.consecutive_loss_halt < 0:
            raise ValueError('consecutive_loss_halt must be non-negative')
        if self.consecutive_loss_halt_side not in ('all', 'short'):
            raise ValueError('consecutive_loss_halt_side must be all or short')
        if not 0 < self.dollar_ratchet_lock_fraction <= 1:
            raise ValueError('dollar_ratchet_lock_fraction must be in (0, 1]')
        if not (0 < self.weekly_loss_fraction < 1
                and 0 < self.drawdown_halt_fraction < 1
                and 0 < self.drawdown_risk_scale_fraction < 1):
            raise ValueError('Invalid halt fractions')
        if self.max_positions < 1:
            raise ValueError('max_positions must be at least 1')


def resample_closed(minutes, interval):
    rule = f'{interval}min'
    bars = minutes.resample(rule, label='right', closed='left').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
        'volume': 'sum', 'taker_buy_volume': 'sum'})
    counts = minutes.close.resample(rule, label='right', closed='left').count()
    return bars.loc[counts == interval].copy()


def volume_profile(frame, bins=48):
    """Contiguous 70% value area, expanded from the maximum-volume bin."""
    prices = (frame.high + frame.low + frame.close) / 3
    histogram, edges = np.histogram(prices, bins=bins, weights=frame.volume)
    poc = int(histogram.argmax())
    left = right = poc
    accumulated = histogram[poc]
    while accumulated < histogram.sum() * 0.7 and (left > 0 or right < bins - 1):
        lower = histogram[left - 1] if left > 0 else -1
        upper = histogram[right + 1] if right < bins - 1 else -1
        if lower >= upper:
            left -= 1
            accumulated += histogram[left]
        else:
            right += 1
            accumulated += histogram[right]
    return {'val': edges[left], 'vah': edges[right + 1],
            'poc': (edges[poc] + edges[poc + 1]) / 2}


def profiles(minutes, mode):
    records = []
    if mode == 'previous_day':
        for day, group in minutes.groupby(minutes.index.floor('D')):
            if len(group) == 1440:
                records.append({'timestamp': day + pd.Timedelta(days=1), **volume_profile(group)})
    else:
        for end in pd.date_range(minutes.index[0].ceil('h') + pd.Timedelta(hours=6),
                                 minutes.index[-1] + pd.Timedelta(minutes=1), freq='h'):
            group = minutes.loc[(minutes.index >= end - pd.Timedelta(hours=6)) & (minutes.index < end)]
            if len(group) == 360:
                records.append({'timestamp': end, **volume_profile(group)})
    if not records:
        return pd.DataFrame(columns=['val', 'vah', 'poc'], index=pd.DatetimeIndex([], tz='UTC'))
    return pd.DataFrame(records).set_index('timestamp')


def divergence_events(bars, side, width=2, max_separation=48):
    """Compare confirmed price pivots; publish only width bars AFTER a pivot.

    Both indicators are sampled at those same price pivots. Never backdate the
    event to the extremum. No centered rolling indicator is exposed as a signal.
    """
    prices = bars.low.to_numpy() if side == 1 else bars.high.to_numpy()
    rsi, cvd = bars.rsi14.to_numpy(), bars.cvd.to_numpy()
    rsi_events = np.zeros(len(bars), dtype=bool)
    cvd_events = np.zeros(len(bars), dtype=bool)
    previous = None
    for known in range(2 * width, len(bars)):
        pivot = known - width
        others = np.r_[prices[pivot-width:pivot], prices[pivot+1:known+1]]
        if not np.all(side * prices[pivot] < side * others):
            continue
        if previous is not None and pivot - previous <= max_separation:
            lower_price = side * (prices[pivot] - prices[previous]) < 0
            rsi_events[known] = lower_price and side * (rsi[pivot] - rsi[previous]) > 0
            cvd_events[known] = lower_price and side * (cvd[pivot] - cvd[previous]) > 0
        previous = pivot
    return rsi_events, cvd_events


def build_features(minutes, interval, profile_mode):
    bars = resample_closed(minutes, interval)
    close = bars.close.to_numpy()
    for length in (9, 20):
        bars[f'ema{length}'] = talib.EMA(close, timeperiod=length)
    for length in (5, 14):
        bars[f'rsi{length}'] = talib.RSI(close, timeperiod=length)
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, timeperiod=14)
    bars['cvd'] = (2 * bars.taker_buy_volume - bars.volume).cumsum()
    higher = resample_closed(minutes, 60)
    higher['ema'] = talib.EMA(higher.close.to_numpy(), timeperiod=20)
    higher['bias'] = np.where((higher.close > higher.ema) & (higher.ema > higher.ema.shift(2)), 1,
                             np.where((higher.close < higher.ema) & (higher.ema < higher.ema.shift(2)), -1, 0))
    higher['adx'] = talib.ADX(higher.high.to_numpy(), higher.low.to_numpy(),
                              higher.close.to_numpy(), timeperiod=14)
    bars['htf_bias'] = higher.bias.reindex(bars.index, method='ffill')
    bars['htf_adx'] = higher.adx.reindex(bars.index, method='ffill')
    bars = bars.join(profiles(minutes, profile_mode).reindex(bars.index, method='ffill'))
    for side, label in ((1, 'long'), (-1, 'short')):
        rsi, cvd = divergence_events(bars, side)
        bars[f'{label}_rsi_div'] = pd.Series(rsi, index=bars.index).rolling(3, min_periods=1).max().astype(bool)
        bars[f'{label}_cvd_div'] = pd.Series(cvd, index=bars.index).rolling(3, min_periods=1).max().astype(bool)
    return bars


def generate_signals(bars, config):
    """Return auditable setups at closed-bar timestamps, ready for NEXT open."""
    candidates = []
    for side, label in ((1, 'long'), (-1, 'short')):
        def recent(event):
            return event.rolling(3, min_periods=1).max().astype(bool)
        fast_recovery = recent((bars.rsi5 > 30) & (bars.rsi5.shift() <= 30)) if side == 1 else recent(
            (bars.rsi5 < 70) & (bars.rsi5.shift() >= 70))
        aligned = side * (bars.close - bars.ema20) > 0
        crossed = recent((side * (bars.ema9 - bars.ema20) > 0)
                         & (side * (bars.ema9.shift() - bars.ema20.shift()) <= 0))
        rsi_div, cvd_div = bars[f'{label}_rsi_div'], bars[f'{label}_cvd_div']
        reversal_score = (fast_recovery.astype(int) + aligned.astype(int) + crossed.astype(int)
                          + rsi_div.astype(int) + cvd_div.astype(int))
        level = bars.val if side == 1 else bars.vah
        extreme = bars.low if side == 1 else bars.high
        reclaim = ((side * (extreme - level) < 0) & (side * (bars.close - level) > 0)
                   & (side * (bars.close - bars.open) > 0))
        reversal = reclaim & (reversal_score >= config.min_score)
        if config.require_divergence:
            reversal &= rsi_div | cvd_div
        if config.mode == 'hybrid':
            reversal &= bars.htf_adx < 25
        if config.mode == 'momentum':
            reversal &= False

        # Continuation uses flow/momentum agreement, not reversal divergences.
        flow = side * bars.cvd.diff(3) > 0
        fast = recent((side * (bars.rsi5 - 50) > 0) & (side * (bars.rsi5.shift() - 50) <= 0))
        stacked = side * (bars.ema9 - bars.ema20) > 0
        slow = side * (bars.rsi14 - 50) > 0
        trend_score = (fast.astype(int) + aligned.astype(int) + stacked.astype(int)
                       + flow.astype(int) + slow.astype(int))
        near_profile = pd.concat([(bars.close - bars[x]).abs() for x in ('val', 'poc', 'vah')], axis=1).min(axis=1) <= bars.atr
        pullback = ((side * (extreme - bars.ema20) <= 0.15 * bars.atr)
                    & aligned & (side * (bars.close - bars.open) > 0))
        continuation = ((bars.htf_bias == side) & pullback & flow
                        & (trend_score >= config.min_score))
        if config.mode == 'hybrid':
            continuation &= near_profile & (bars.htf_adx >= 20)
        elif config.mode == 'reclaim':
            continuation &= False
        stop = (bars.low.rolling(3).min() - 0.2 * bars.atr if side == 1
                else bars.high.rolling(3).max() + 0.2 * bars.atr)
        risk = side * (bars.close - stop)
        # Avoid a target beyond the known POC in the reversal setup.
        reversal &= side * (bars.poc - bars.close) >= config.target_r * risk
        selected = (reversal | continuation) & bars.atr.notna() & (risk > 0)
        for i in np.flatnonzero(selected.to_numpy()):
            is_reversal = bool(reversal.iloc[i])
            candidates.append({'timestamp': bars.index[i], 'side': side,
                               'stop': float(stop.iloc[i]), 'atr': float(bars.atr.iloc[i]),
                               'reference': float(bars.close.iloc[i]),
                               'target_boundary': float(bars.poc.iloc[i]) if is_reversal else None,
                               'score': int(reversal_score.iloc[i] if is_reversal else trend_score.iloc[i]),
                               'setup': 'reclaim' if is_reversal else 'continuation',
                               'rsi_div': bool(rsi_div.iloc[i]), 'cvd_div': bool(cvd_div.iloc[i])})
    candidates.sort(key=lambda x: x['timestamp'])
    # Conflicting directions at the same timestamp mean no trade.
    counts = pd.Series([x['timestamp'] for x in candidates]).value_counts()
    return [x for x in candidates if counts[x['timestamp']] == 1]
