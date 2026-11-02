"""Causal entry-policy transforms for the frozen S20 OB+OI candidate stream.

The parent detector decides direction, zone, regime, flow and OI confirmation.
This module changes only *when* the already-qualified setup becomes executable:
immediate market, sweep/reclaim on the touch bar, later 5m MSS, or MSS retest.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scalp_strategy import resample_closed


@dataclass(frozen=True)
class S20EntryLabConfig:
    liquidity_lookback_bars: int = 8
    mss_window_minutes: int = 30
    mss_break_atr: float = 0.03
    retest_ttl_minutes: int = 30

    def __post_init__(self) -> None:
        if self.liquidity_lookback_bars < 2:
            raise ValueError('Liquidity lookback must be at least two bars')
        if self.mss_window_minutes < 5 or self.mss_window_minutes % 5:
            raise ValueError('MSS window must be a positive multiple of five minutes')
        if not 0 <= self.mss_break_atr < 1:
            raise ValueError('Invalid MSS break buffer')
        if self.retest_ttl_minutes < 1:
            raise ValueError('Retest TTL must be positive')


ENTRY_POLICIES = ('MARKET_TOUCH', 'SWEEP_RECLAIM', 'MSS_BREAK', 'MSS_RETEST')


def _copy_signal(signal: dict, policy: str, **changes) -> dict:
    evidence = dict(signal.get('evidence') or {})
    evidence.update(changes.pop('evidence', {}))
    result = {
        **signal,
        **changes,
        'setup': f's20_entry_lab_{policy.lower()}',
        'setup_id': f'{signal.get("setup_id", "S20")}:ENTRY:{policy}',
        'evidence': evidence,
    }
    return result


def build_s20_entry_variants(
    minutes: pd.DataFrame,
    bars: pd.DataFrame,
    parent_signals: list[dict],
    config: S20EntryLabConfig = S20EntryLabConfig(),
) -> dict[str, list[dict]]:
    """Build four causal variants from one immutable parent signal cohort."""
    five = resample_closed(minutes, 5)
    prior_low = bars.low.shift(1).rolling(
        config.liquidity_lookback_bars,
        min_periods=config.liquidity_lookback_bars,
    ).min()
    prior_high = bars.high.shift(1).rolling(
        config.liquidity_lookback_bars,
        min_periods=config.liquidity_lookback_bars,
    ).max()
    result = {policy: [] for policy in ENTRY_POLICIES}

    for signal in parent_signals:
        timestamp = signal['timestamp']
        if timestamp not in bars.index:
            continue
        touch = bars.loc[timestamp]
        side = int(signal['side'])
        common_evidence = {
            'parent_setup_id': signal.get('setup_id'),
            'parent_timestamp': timestamp.isoformat(),
            'touch_high': float(touch.high),
            'touch_low': float(touch.low),
        }
        result['MARKET_TOUCH'].append(_copy_signal(
            signal, 'MARKET_TOUCH', evidence=common_evidence,
        ))

        liquidity = prior_low.loc[timestamp] if side == 1 else prior_high.loc[timestamp]
        if np.isfinite(liquidity):
            reclaimed = (
                touch.low < liquidity and touch.close > liquidity
                if side == 1
                else touch.high > liquidity and touch.close < liquidity
            )
            directional = touch.close > touch.open if side == 1 else touch.close < touch.open
            if reclaimed and directional:
                result['SWEEP_RECLAIM'].append(_copy_signal(
                    signal,
                    'SWEEP_RECLAIM',
                    evidence={**common_evidence, 'liquidity_level': float(liquidity)},
                ))

        atr = float(signal['atr'])
        break_level = float(touch.high if side == 1 else touch.low)
        threshold = break_level + side * config.mss_break_atr * atr
        deadline = timestamp + pd.Timedelta(minutes=config.mss_window_minutes)
        future = five.loc[(five.index > timestamp) & (five.index <= deadline)]
        confirmation = None
        for known_at, row in future.iterrows():
            broke = side * (float(row.close) - threshold) >= 0
            directional = row.close > row.open if side == 1 else row.close < row.open
            if broke and directional:
                confirmation = (known_at, row)
                break
        if confirmation is None:
            continue

        known_at, confirm_bar = confirmation
        confirm_evidence = {
            **common_evidence,
            'mss_known_at': known_at.isoformat(),
            'mss_break_level': break_level,
            'mss_close': float(confirm_bar.close),
        }
        result['MSS_BREAK'].append(_copy_signal(
            signal,
            'MSS_BREAK',
            timestamp=known_at,
            reference=float(confirm_bar.close),
            evidence=confirm_evidence,
        ))

        limit_risk = side * (break_level - float(signal['stop']))
        if limit_risk > 0:
            result['MSS_RETEST'].append(_copy_signal(
                signal,
                'MSS_RETEST',
                timestamp=known_at,
                reference=float(confirm_bar.close),
                limit_price=break_level,
                limit_ttl_minutes=config.retest_ttl_minutes,
                evidence=confirm_evidence,
            ))

    for policy, records in result.items():
        records.sort(key=lambda row: row['timestamp'])
        counts = Counter(row['timestamp'] for row in records)
        result[policy] = [row for row in records if counts[row['timestamp']] == 1]
    return result
