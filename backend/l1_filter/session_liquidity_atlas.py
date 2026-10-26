"""Causal prior-day, prior-week and Asia-session liquidity atlas for S109."""
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .liquidity_sweep_failed_auction import (
    FailedAuctionConfig,
    build_failed_auction_features,
    generate_failed_auction_signals_from_bars,
)


@dataclass(frozen=True)
class SessionLiquidityAtlasConfig:
    previous_day_weight: int = 2
    previous_week_weight: int = 3
    asia_session_weight: int = 1
    asia_end_hour_utc: int = 8
    alignment_tolerance_atr: float = 0.25
    repeated_touch_bonus_cap: int = 2
    minimum_strength_score: int = 2
    touch_lookback_bars: int = 96
    confirmation_window_bars: int = 6

    def validate(self) -> None:
        if min(
            self.previous_day_weight,
            self.previous_week_weight,
            self.asia_session_weight,
        ) < 1:
            raise ValueError('Atlas weights must be positive')
        if not 1 <= self.asia_end_hour_utc <= 23:
            raise ValueError('Invalid Asia end hour')
        if not 0 < self.alignment_tolerance_atr <= 1:
            raise ValueError('Invalid anchor-alignment tolerance')
        if self.repeated_touch_bonus_cap < 0:
            raise ValueError('Invalid repeated-touch bonus')
        if self.minimum_strength_score < 1 or self.touch_lookback_bars < 8:
            raise ValueError('Invalid atlas strength policy')
        if self.confirmation_window_bars < 1:
            raise ValueError('Invalid confirmation window')

    def failed_auction(self) -> FailedAuctionConfig:
        self.validate()
        return replace(
            FailedAuctionConfig(),
            confirmation_window_bars=self.confirmation_window_bars,
            minimum_level_touches=self.minimum_strength_score,
        )


def _completed_anchor_tables(bars: pd.DataFrame, asia_end_hour: int):
    source_day = (bars.index - pd.Timedelta(microseconds=1)).normalize()
    source_week = source_day - pd.to_timedelta(source_day.weekday, unit='D')
    daily = bars.groupby(source_day).agg({'high': 'max', 'low': 'min'})
    weekly = bars.groupby(source_week).agg({'high': 'max', 'low': 'min'})
    decision_day = bars.index.normalize()
    minute_of_day = bars.index.hour * 60 + bars.index.minute
    asia_mask = (minute_of_day > 0) & (minute_of_day <= asia_end_hour * 60)
    asia = bars.loc[asia_mask].groupby(decision_day[asia_mask]).agg({
        'high': 'max', 'low': 'min'})
    return daily, weekly, asia


def _candidate_level(
    anchors: list[tuple[float, int]],
    history: np.ndarray,
    current_extreme: float,
    current_close: float,
    atr: float,
    side: int,
    atlas: SessionLiquidityAtlasConfig,
    sweep_buffer_atr: float,
) -> tuple[float, int]:
    tolerance = atlas.alignment_tolerance_atr * atr
    sweep_buffer = sweep_buffer_atr * atr
    choices = []
    for level, _ in anchors:
        if not np.isfinite(level):
            continue
        swept = (
            current_extreme < level - sweep_buffer and current_close > level
            if side == 1 else
            current_extreme > level + sweep_buffer and current_close < level)
        if not swept:
            continue
        aligned_weight = sum(
            weight for other, weight in anchors
            if np.isfinite(other) and abs(other - level) <= tolerance)
        touches = int(np.sum(np.abs(history - level) <= tolerance))
        repeated_bonus = min(
            atlas.repeated_touch_bonus_cap, max(0, touches - 1))
        strength = aligned_weight + repeated_bonus
        choices.append((strength, -abs(current_close - level), level))
    if not choices:
        return np.nan, 0
    strength, _, level = max(choices)
    return float(level), int(strength)


def apply_session_liquidity_atlas(
    bars: pd.DataFrame,
    atlas: SessionLiquidityAtlasConfig = SessionLiquidityAtlasConfig(),
    strategy: FailedAuctionConfig | None = None,
) -> pd.DataFrame:
    """Replace rolling sweep levels with causally available named anchors."""
    atlas.validate()
    strategy = strategy or atlas.failed_auction()
    strategy.validate()
    required = {
        'high', 'low', 'close', 'atr',
        'prior_target_liquidity_high', 'prior_target_liquidity_low',
    }
    if not required.issubset(bars):
        raise ValueError(f'Atlas input lacks {sorted(required - set(bars))}')
    result = bars.copy()
    daily, weekly, asia = _completed_anchor_tables(
        result, atlas.asia_end_hour_utc)
    highs = result.high.to_numpy(dtype=float)
    lows = result.low.to_numpy(dtype=float)
    selected_high = np.full(len(result), np.nan)
    selected_low = np.full(len(result), np.nan)
    high_strength = np.zeros(len(result), dtype=int)
    low_strength = np.zeros(len(result), dtype=int)

    for index, (timestamp, row) in enumerate(result.iterrows()):
        if not np.isfinite(row.atr) or row.atr <= 0:
            continue
        day = timestamp.normalize()
        week = day - pd.Timedelta(days=day.weekday())
        prior_day = day - pd.Timedelta(days=1)
        prior_week = week - pd.Timedelta(days=7)
        high_anchors, low_anchors = [], []
        if prior_day in daily.index:
            high_anchors.append((float(daily.loc[prior_day, 'high']),
                                 atlas.previous_day_weight))
            low_anchors.append((float(daily.loc[prior_day, 'low']),
                                atlas.previous_day_weight))
        if prior_week in weekly.index:
            high_anchors.append((float(weekly.loc[prior_week, 'high']),
                                 atlas.previous_week_weight))
            low_anchors.append((float(weekly.loc[prior_week, 'low']),
                                atlas.previous_week_weight))
        if (timestamp > day + pd.Timedelta(hours=atlas.asia_end_hour_utc)
                and day in asia.index):
            high_anchors.append((float(asia.loc[day, 'high']),
                                 atlas.asia_session_weight))
            low_anchors.append((float(asia.loc[day, 'low']),
                                atlas.asia_session_weight))
        start = max(0, index - atlas.touch_lookback_bars)
        selected_high[index], high_strength[index] = _candidate_level(
            high_anchors, highs[start:index], float(row.high), float(row.close),
            float(row.atr), -1, atlas, strategy.sweep_buffer_atr)
        selected_low[index], low_strength[index] = _candidate_level(
            low_anchors, lows[start:index], float(row.low), float(row.close),
            float(row.atr), 1, atlas, strategy.sweep_buffer_atr)

    result['prior_liquidity_high'] = selected_high
    result['prior_liquidity_low'] = selected_low
    result['prior_high_touches'] = high_strength
    result['prior_low_touches'] = low_strength
    return result


def generate_session_atlas_signals(
    prices_5m: pd.DataFrame,
    metrics_5m: pd.DataFrame,
    funding: pd.Series,
    regimes: pd.DataFrame | pd.Series,
    symbol: str,
    atlas: SessionLiquidityAtlasConfig = SessionLiquidityAtlasConfig(),
) -> tuple[list[dict], dict]:
    strategy = atlas.failed_auction()
    bars = build_failed_auction_features(
        prices_5m, metrics_5m, funding, strategy)
    bars = apply_session_liquidity_atlas(bars, atlas, strategy)
    signals, diagnostics = generate_failed_auction_signals_from_bars(
        bars, regimes, symbol, strategy)
    diagnostics['atlas_config'] = {
        'previous_day_weight': atlas.previous_day_weight,
        'previous_week_weight': atlas.previous_week_weight,
        'asia_session_weight': atlas.asia_session_weight,
        'asia_end_hour_utc': atlas.asia_end_hour_utc,
        'alignment_tolerance_atr': atlas.alignment_tolerance_atr,
        'repeated_touch_bonus_cap': atlas.repeated_touch_bonus_cap,
        'minimum_strength_score': atlas.minimum_strength_score,
        'touch_lookback_bars': atlas.touch_lookback_bars,
        'confirmation_window_bars': atlas.confirmation_window_bars,
    }
    return signals, diagnostics
