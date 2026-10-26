"""S7 v2: separate market mechanisms, cost-aware stops, no indicator voting.

These hypotheses remain research-only until independent testing supports them.
All features use completed candles; no fitted per-symbol thresholds.
"""
from dataclasses import dataclass, replace
from collections import Counter

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class RevisionConfig:
    name: str
    setup: str
    minutes: int = 5
    exit_style: str = 'fixed'
    stop_atr: float = 1.5
    target_r: float = 3.0
    max_hold: int = 240
    entry_style: str = 'market'
    leverage: float = 1.0

    def execution(self):
        return ScalpConfig(name=self.name, minutes=self.minutes, mode='hybrid',
                           profile='rolling_6h', target_r=self.target_r,
                           partial_r=min(2.0, self.target_r - .25), partial_fraction=0,
                           trailing=self.exit_style == 'trail', trail_atr=2.5,
                           max_hold_minutes=self.max_hold, min_reward_cost_ratio=4,
                           leverage=self.leverage,
                           max_notional_equity=3 if self.leverage > 1 else 1,
                           max_margin_fraction=.15 if self.leverage > 1 else 1)


def revision_variants():
    result = []
    for setup in ('absorption', 'exhaustion', 'breakout_retest'):
        for minutes in (5, 15):
            base = RevisionConfig(f'S7v2_{setup}_{minutes}m_3R', setup, minutes)
            result.extend([base, replace(base, name=f'S7v2_{setup}_{minutes}m_4Rtrail',
                                         target_r=4, exit_style='trail', max_hold=360)])
    return result


def revision_features(minutes, interval):
    bars = resample_closed(minutes, interval)
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy(), 14)
    bars['rsi5'] = talib.RSI(bars.close.to_numpy(), 5)
    bars['ema20'] = talib.EMA(bars.close.to_numpy(), 20)
    bars['delta_ratio'] = (2 * bars.taker_buy_volume - bars.volume) / bars.volume.replace(0, np.nan)
    bars['relative_volume'] = bars.volume / bars.volume.shift().rolling(48).median()
    typical = (bars.high + bars.low + bars.close) / 3
    # Fixed rolling six-hour volume-weighted value; no full-session future data.
    window = 360 // interval
    bars['value'] = (typical * bars.volume).rolling(window).sum() / bars.volume.rolling(window).sum()
    bars['prior_high'] = bars.high.shift().rolling(12).max()
    bars['prior_low'] = bars.low.shift().rolling(12).min()
    bars['channel_high'] = bars.high.shift().rolling(24).max()
    bars['channel_low'] = bars.low.shift().rolling(24).min()
    width = bars.close.rolling(20).std() / bars.close.rolling(20).mean()
    bars['compressed'] = width.shift() < width.shift().rolling(96).quantile(.5)
    higher = resample_closed(minutes, 60)
    higher['ema20'] = talib.EMA(higher.close.to_numpy(), 20)
    higher['ema50'] = talib.EMA(higher.close.to_numpy(), 50)
    higher['adx'] = talib.ADX(higher.high.to_numpy(), higher.low.to_numpy(), higher.close.to_numpy(), 14)
    higher['bias'] = np.where((higher.close > higher.ema20) & (higher.ema20 > higher.ema50), 1,
                              np.where((higher.close < higher.ema20) & (higher.ema20 < higher.ema50), -1, 0))
    for name in ('adx', 'bias'):
        bars[f'htf_{name}'] = higher[name].reindex(bars.index, method='ffill')
    bars['close_location'] = (bars.close - bars.low) / (bars.high - bars.low).replace(0, np.nan)
    return bars


def revision_signals(bars, config):
    records = []
    for side in (1, -1):
        close_location = bars.close_location if side == 1 else 1 - bars.close_location
        extreme = bars.low if side == 1 else bars.high
        prior = bars.prior_low if side == 1 else bars.prior_high
        response = (close_location >= .65) & (side * (bars.close - bars.open) > 0)
        if config.setup in ('channel_breakout', 'squeeze_breakout'):
            level = bars.channel_high if side == 1 else bars.channel_low
            selected = ((side * (bars.close - level) > 0) & (close_location >= .65)
                        & (bars.htf_bias == side))
            if config.setup == 'squeeze_breakout':
                selected &= bars.compressed & (bars.relative_volume >= 1.2)
        elif config.setup == 'range_sweep':
            selected = ((side * (extreme - prior) < 0) & (side * (bars.close - prior) > 0)
                        & response & (bars.htf_adx < 25)
                        & (side * (bars.close - bars.value) < 0))
        elif config.setup == 'absorption':
            # Aggressive sellers fail to sustain a new low (vice versa for short).
            # Order flow opposes the reversal; price acceptance is what matters.
            selected = ((side * (extreme - prior) < 0) & (side * (bars.close - prior) > 0)
                        & response & (side * bars.delta_ratio < -.05)
                        & (bars.relative_volume >= 1.2)
                        & ((bars.htf_adx < 30) | (bars.htf_bias == side)))
        elif config.setup == 'exhaustion':
            # Extended price snaps back toward six-hour volume-weighted value.
            extended = side * (extreme - bars.value) < -2 * bars.atr
            rsi_extreme = bars.rsi5.shift().rolling(3).min() < 20 if side == 1 else bars.rsi5.shift().rolling(3).max() > 80
            selected = (extended & rsi_extreme & response & (bars.relative_volume >= 1.2)
                        & ((bars.htf_adx < 30) | (bars.htf_bias == side)))
        elif config.setup == 'breakout_retest':
            breakout_level = bars.prior_high if side == 1 else bars.prior_low
            breakout = ((side * (bars.close - breakout_level) > 0) & (close_location > .75)
                        & (bars.relative_volume > 1.5) & (side * bars.delta_ratio > .1)
                        & (bars.htf_bias == side) & (bars.htf_adx >= 20))
            # A breakout only becomes eligible on subsequent bars, expires in 6.
            level = breakout_level.where(breakout).shift().ffill(limit=5)
            selected = ((side * (extreme - level) <= .15 * bars.atr)
                        & (side * (bars.close - level) > 0) & response
                        & (side * bars.delta_ratio > 0) & (bars.htf_bias == side))
        else:
            raise ValueError(config.setup)
        # One signal per episode. Require at least three bars between events;
        # this prevents the same pullback from producing repeated fresh entries.
        selected = selected.fillna(False)
        last = -100
        for i in np.flatnonzero(selected.to_numpy()):
            if i - last < 3:
                continue
            row = bars.iloc[i]
            atr = row.atr
            # At least 2x assumed full-round-trip costs per initial R.
            minimum_r = 2 * 2 * row.close * (.0005 + .0002)
            structural_r = side * (row.close - extreme.iloc[i]) + .25 * atr
            risk = max(config.stop_atr * atr, structural_r, minimum_r)
            if not np.isfinite(risk) or risk > 3 * atr:
                continue
            last = i
            record = {'timestamp': bars.index[i], 'side': side,
                            'reference': float(row.close), 'stop': float(row.close - side * risk),
                            'atr': float(atr), 'score': 0, 'setup': config.setup}
            if config.entry_style == 'limit':
                record['limit_price'] = float(row.close - side * .35 * atr)
                record['limit_ttl_minutes'] = min(3 * config.minutes, 30)
            records.append(record)
    records.sort(key=lambda x: x['timestamp'])
    counts = Counter(x['timestamp'] for x in records)
    return [x for x in records if counts[x['timestamp']] == 1]
