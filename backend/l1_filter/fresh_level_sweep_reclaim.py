"""S90: causal fresh order-block / support-resistance sweep reclaim.

The level is only an observation area.  A candidate is published from closed
1h bars after a break of an already-confirmed swing and must overlap a causal
4h swing.  Execution is deliberately handled separately: no order is placed
until the first return sweeps the zone and reclaims it.
"""
from collections import deque
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scalp_strategy import ScalpConfig, resample_closed
from .strong_level_retest import confirmed_swings, prepare_four_hour_bars


@dataclass(frozen=True)
class FreshLevelSweepReclaimConfig:
    name: str = 'S90_fresh_level_sweep_reclaim'
    level_minutes: int = 60
    htf_minutes: int = 240
    swing_width: int = 2
    structure_lookback: int = 240
    order_block_search_bars: int = 3
    displacement_atr: float = 1.20
    volume_multiple: float = 1.25
    max_zone_atr: float = 0.90
    htf_distance_atr: float = 0.35
    min_score: float = 75.0
    validity_hours: int = 120
    departure_atr: float = 0.10
    merge_midpoint_atr: float = 0.25
    min_sweep_atr: float = 0.05
    max_sweep_atr: float = 0.50
    reclaim_minutes: int = 30
    max_entry_chase_atr: float = 0.20
    stop_buffer_atr: float = 0.10
    min_stop_atr: float = 0.35
    max_stop_atr: float = 1.50
    target_net_r: float = 2.0
    require_distal_sweep: bool = True

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=5,
            target_r=3.0,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=24 * 60,
            risk_fraction=0.0020,
            max_notional_equity=0.50,
            daily_loss_fraction=0.010,
            weekly_loss_fraction=0.018,
            drawdown_risk_scale_fraction=0.040,
            drawdown_halt_fraction=0.060,
            fee_bps=5.0,
            maker_fee_bps=2.0,
            slippage_bps=2.0,
            limit_penetration_bps=2.0,
            min_reward_cost_ratio=0.0,
            leverage=5.0,
            max_margin_fraction=0.20,
            margin_safety_reserve=0.01,
            max_positions=1,
        )


def level_strength_score(
    displacement_ratio: float,
    volume_ratio: float,
    htf_confluence: bool,
    imbalance_ratio: float,
    trend_aligned: bool,
) -> tuple[float, dict[str, float]]:
    """Frozen, transparent quality score; touch count is intentionally absent."""
    components = {
        'confirmed_structure_break': 25.0,
        'displacement': float(np.clip(
            10.0 + (displacement_ratio - 1.20) * 12.5, 0.0, 20.0)),
        'htf_location': 20.0 if htf_confluence else 0.0,
        'imbalance': float(np.clip(imbalance_ratio * 30.0, 0.0, 15.0)),
        'relative_volume': float(np.clip(
            5.0 + (volume_ratio - 1.25) * 10.0, 0.0, 10.0)),
        'trend_alignment': 10.0 if trend_aligned else 0.0,
    }
    return float(sum(components.values())), components


def _available_swing_prices(bars, swings, timestamp) -> list[float]:
    return [
        float(price)
        for _, confirmation, price in swings
        if bars.index[confirmation] <= timestamp
    ]


def _nearest_ahead(side: int, price: float, levels: list[float]) -> float | None:
    ahead = [value for value in levels if side * (value - price) > 0]
    if not ahead:
        return None
    return min(ahead) if side == 1 else max(ahead)


def _latest_eligible_by_bar(swings, bar_count: int, lookback: int):
    """O(n) equivalent of selecting the latest causal swing for every bar."""
    out = [None] * bar_count
    active = deque()
    cursor = 0
    for known in range(bar_count):
        while cursor < len(swings) and swings[cursor][1] < known:
            active.append(swings[cursor])
            cursor += 1
        oldest = max(0, known - lookback)
        while active and active[0][0] < oldest:
            active.popleft()
        if active:
            out[known] = active[-1]
    return out


def fresh_level_candidates(
    minutes: pd.DataFrame,
    config: FreshLevelSweepReclaimConfig,
) -> tuple[pd.DataFrame, list[dict]]:
    """Build immutable 1h candidates from information known at publication."""
    bars = prepare_four_hour_bars(resample_closed(minutes, config.level_minutes))
    four_hour = prepare_four_hour_bars(resample_closed(minutes, config.htf_minutes))
    high_swings, low_swings = confirmed_swings(bars, config.swing_width)
    high_4h, low_4h = confirmed_swings(four_hour, config.swing_width)
    rows = list(bars.itertuples())
    latest_high = _latest_eligible_by_bar(
        high_swings, len(rows), config.structure_lookback)
    latest_low = _latest_eligible_by_bar(
        low_swings, len(rows), config.structure_lookback)
    events: list[dict] = []

    for known in range(max(24, 2 * config.swing_width), len(rows)):
        end = rows[known]
        previous = rows[known - 1]
        if (not np.isfinite(end.atr) or end.atr <= 0
                or not np.isfinite(end.volume_median20)
                or end.volume_median20 <= 0):
            continue

        for side in (1, -1):
            broken = latest_high[known] if side == 1 else latest_low[known]
            if broken is None:
                continue
            broken_price = broken[2]
            if (side * (end.close - broken_price) < 0.05 * end.atr
                    or side * (previous.close - broken_price) >= 0.05 * end.atr):
                continue

            body_displacement = side * (end.close - end.open) / end.atr
            if body_displacement < config.displacement_atr:
                continue
            candle_range = max(end.high - end.low, 1e-12)
            close_location = (
                (end.close - end.low) / candle_range if side == 1
                else (end.high - end.close) / candle_range
            )
            if close_location < 0.70:
                continue
            volume_ratio = float(end.volume / end.volume_median20)
            if volume_ratio < config.volume_multiple:
                continue

            # Exactly one OB per displacement: the last opposing candle.
            ob_i = next((
                index for index in range(known - 1, max(-1, known - 1 - config.order_block_search_bars), -1)
                if side * (rows[index].close - rows[index].open) < 0
                and broken[1] <= index
            ), None)
            if ob_i is None:
                continue
            ob = rows[ob_i]
            bottom = float(ob.low if side == 1 else ob.open)
            top = float(ob.open if side == 1 else ob.high)
            if top <= bottom:
                continue
            width_ratio = (top - bottom) / end.atr
            if not 0.10 <= width_ratio <= config.max_zone_atr:
                continue
            midpoint = 0.5 * (bottom + top)
            displacement = side * (end.close - midpoint) / end.atr
            if displacement < config.displacement_atr:
                continue

            htf_swings = low_4h if side == 1 else high_4h
            htf_prices = _available_swing_prices(four_hour, htf_swings, end.Index)
            if not htf_prices:
                continue
            htf_level = min(htf_prices, key=lambda price: abs(price - midpoint))
            htf_distance = abs(htf_level - midpoint) / end.atr
            if htf_distance > config.htf_distance_atr:
                continue

            anchor = rows[known - 2]
            gap = (
                max(0.0, end.low - anchor.high) if side == 1
                else max(0.0, anchor.low - end.high)
            )
            imbalance_ratio = gap / end.atr
            trend_aligned = bool(
                np.isfinite(end.ema50) and np.isfinite(end.ema200)
                and side * (end.ema50 - end.ema200) > 0
            )
            score, components = level_strength_score(
                displacement, volume_ratio, True, imbalance_ratio, trend_aligned)
            if score < config.min_score:
                continue

            opposing = _available_swing_prices(
                bars, low_swings if side == 1 else high_swings, end.Index)
            boundary = _nearest_ahead(side, midpoint, opposing)
            setup_id = f'{side}:{ob.Index.isoformat()}:{end.Index.isoformat()}'
            events.append({
                'timestamp': end.Index,
                'created_at': end.Index,
                'ob_close_time': ob.Index,
                'side': side,
                'reference': float(end.close),
                'atr': float(end.atr),
                'score': float(score),
                'setup': config.name,
                'setup_id': setup_id,
                'order_block': [bottom, top],
                'limit_ttl_minutes': config.validity_hours * 60,
                'target_boundary': boundary,
                'evidence': {
                    'score_components': components,
                    'broken_structure': float(broken_price),
                    'displacement_atr': float(displacement),
                    'relative_volume': volume_ratio,
                    'htf_level': float(htf_level),
                    'htf_distance_atr': float(htf_distance),
                    'imbalance_atr': float(imbalance_ratio),
                    'trend_aligned': trend_aligned,
                    'zone_timeframe_minutes': config.level_minutes,
                    'confluence_timeframe_minutes': config.htf_minutes,
                },
            })

    events.sort(key=lambda item: (item['timestamp'], -item['score'], item['setup_id']))
    return bars, events
