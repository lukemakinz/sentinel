"""S87: pre-armed first retest of a strong order-block/SR confluence.

The module is deliberately research-only.  A zone is published at the close
of a 4h confirmation candle, after an already-confirmed swing has been broken.
The resting limit therefore exists *before* the first future retest.  Pivots
are never backdated and every value used by a signal was available at its
``timestamp``.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class StrongLevelRetestConfig:
    name: str = 'S87_strong_level_retest'
    swing_width: int = 2
    structure_lookback: int = 90
    cluster_atr: float = 0.35
    min_prior_touches: int = 2
    displacement_atr: float = 1.20
    volume_multiple: float = 1.20
    min_score: float = 70.0
    entry_fraction: float = 0.50
    stop_buffer_atr: float = 0.20
    validity_hours: int = 72
    target_r: float = 3.0
    min_target_r: float = 2.0

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=15,
            target_r=self.target_r,
            partial_r=1.5,
            partial_fraction=0.0,
            trailing=False,
            trail_atr=1.0,
            max_hold_minutes=3 * 24 * 60,
            risk_fraction=0.0020,
            max_notional_equity=1.0,
            daily_loss_fraction=0.010,
            weekly_loss_fraction=0.018,
            drawdown_risk_scale_fraction=0.040,
            drawdown_halt_fraction=0.060,
            fee_bps=5.0,
            maker_fee_bps=2.0,
            slippage_bps=2.0,
            limit_penetration_bps=2.0,
            min_reward_cost_ratio=4.0,
            leverage=5.0,
            max_margin_fraction=0.20,
            margin_safety_reserve=0.01,
            max_positions=1,
        )


def confirmed_swings(
    bars: pd.DataFrame,
    width: int = 2,
) -> tuple[list[tuple[int, int, float]], list[tuple[int, int, float]]]:
    """Return ``(pivot, confirmation, price)`` without future leakage."""
    highs, lows = bars.high.to_numpy(), bars.low.to_numpy()
    swing_highs: list[tuple[int, int, float]] = []
    swing_lows: list[tuple[int, int, float]] = []
    for known in range(2 * width, len(bars)):
        pivot = known - width
        high_window = highs[pivot - width:pivot + width + 1]
        low_window = lows[pivot - width:pivot + width + 1]
        if highs[pivot] == np.max(high_window):
            swing_highs.append((pivot, known, float(highs[pivot])))
        if lows[pivot] == np.min(low_window):
            swing_lows.append((pivot, known, float(lows[pivot])))
    return swing_highs, swing_lows


def level_strength_score(
    *,
    displacement_ratio: float,
    volume_ratio: float,
    prior_touches: int,
    trend_aligned: bool,
    zone_width_ratio: float,
) -> tuple[float, dict[str, float]]:
    """Transparent 0-100 score; there is no learned or fitted component."""
    components = {
        'structure_break': 25.0,
        'displacement': float(np.clip(
            10.0 + (displacement_ratio - 1.20) * 12.5, 0.0, 20.0)),
        'origin_volume': float(np.clip(
            8.0 + (volume_ratio - 1.20) * 8.75, 0.0, 15.0)),
        'sr_confluence': float(np.clip(
            10.0 + (prior_touches - 2) * 5.0, 0.0, 20.0)),
        'trend_alignment': 10.0 if trend_aligned else 0.0,
        'zone_geometry': 5.0 if 0.20 <= zone_width_ratio <= 0.90 else 0.0,
        'fresh_first_retest': 5.0,
    }
    return float(sum(components.values())), components


def four_hour_features(minutes: pd.DataFrame) -> pd.DataFrame:
    bars = resample_closed(minutes, 240)
    return prepare_four_hour_bars(bars)


def prepare_four_hour_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Add causal indicators to already-complete 4h bars (also useful in tests)."""
    bars = bars.copy()
    bars['atr'] = talib.ATR(
        bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy(), 14)
    bars['volume_median20'] = bars.volume.shift().rolling(20).median()
    bars['ema50'] = talib.EMA(bars.close.to_numpy(), timeperiod=50)
    bars['ema200'] = talib.EMA(bars.close.to_numpy(), timeperiod=200)
    return bars


def _recent_swings(swings, ob_i: int, lookback: int):
    return [
        (pivot, confirmed, price)
        for pivot, confirmed, price in swings
        if max(0, ob_i - lookback) <= pivot < ob_i and confirmed <= ob_i
    ]


def _nearest_target_boundary(side: int, entry: float, swings) -> float | None:
    prices = [price for _, _, price in swings if side * (price - entry) > 0]
    if not prices:
        return None
    return min(prices) if side == 1 else max(prices)


def strong_level_events_from_bars(
    bars: pd.DataFrame,
    config: StrongLevelRetestConfig,
) -> list[dict]:
    """Detect and score zones from complete 4h bars."""
    required = {'atr', 'volume_median20', 'ema50', 'ema200'}
    if not required.issubset(bars.columns):
        bars = prepare_four_hour_bars(bars)
    swings_high, swings_low = confirmed_swings(bars, config.swing_width)
    rows = list(bars.itertuples())
    events: list[dict] = []
    published: set[tuple[int, pd.Timestamp]] = set()

    for known in range(max(24, 2 * config.swing_width), len(rows)):
        end = rows[known]
        if (not np.isfinite(end.atr) or end.atr <= 0
                or not np.isfinite(end.volume_median20)):
            continue
        for ob_i in range(max(0, known - 3), known):
            ob = rows[ob_i]
            for side in (1, -1):
                if side * (ob.close - ob.open) >= 0:
                    continue
                setup_key = (side, ob.Index)
                if setup_key in published:
                    continue

                opposing = _recent_swings(
                    swings_high if side == 1 else swings_low,
                    ob_i,
                    config.structure_lookback,
                )
                if not opposing:
                    continue
                # The latest confirmed swing defines a causal break of structure.
                broken = max(opposing, key=lambda item: item[0])[2]
                if side * (end.close - broken) < 0.05 * end.atr:
                    continue

                bottom = float(ob.low if side == 1 else ob.open)
                top = float(ob.open if side == 1 else ob.high)
                width_ratio = (top - bottom) / end.atr
                if not 0.20 <= width_ratio <= 0.90:
                    continue
                midpoint = bottom + config.entry_fraction * (top - bottom)
                displacement = side * (end.close - midpoint) / end.atr
                if displacement < config.displacement_atr:
                    continue

                impulse_volume_ratio = 0.0
                for candle in rows[ob_i + 1:known + 1]:
                    if not (np.isfinite(candle.atr)
                            and np.isfinite(candle.volume_median20)
                            and candle.volume_median20 > 0):
                        continue
                    candle_range = max(candle.high - candle.low, 1e-12)
                    close_location = (
                        (candle.close - candle.low) / candle_range if side == 1
                        else (candle.high - candle.close) / candle_range)
                    if (side * (candle.close - candle.open) >= 0.60 * candle.atr
                            and close_location >= 0.70):
                        impulse_volume_ratio = max(
                            impulse_volume_ratio,
                            float(candle.volume / candle.volume_median20),
                        )
                if impulse_volume_ratio < config.volume_multiple:
                    continue

                same_side = _recent_swings(
                    swings_low if side == 1 else swings_high,
                    ob_i,
                    config.structure_lookback,
                )
                tolerance = config.cluster_atr * end.atr
                matching = [
                    item for item in same_side
                    if abs(item[2] - midpoint) <= tolerance
                ]
                if len(matching) < config.min_prior_touches:
                    continue

                trend_aligned = bool(
                    np.isfinite(end.ema50)
                    and np.isfinite(end.ema200)
                    and side * (end.ema50 - end.ema200) > 0
                    and known >= 4
                    and side * (end.ema50 - rows[known - 4].ema50) > 0
                )
                score, components = level_strength_score(
                    displacement_ratio=displacement,
                    volume_ratio=impulse_volume_ratio,
                    prior_touches=len(matching),
                    trend_aligned=trend_aligned,
                    zone_width_ratio=width_ratio,
                )
                if score < config.min_score:
                    continue

                stop = (
                    bottom - config.stop_buffer_atr * end.atr if side == 1
                    else top + config.stop_buffer_atr * end.atr
                )
                risk = side * (midpoint - stop)
                if not 0.20 * end.atr <= risk <= 1.50 * end.atr:
                    continue

                current_swings = [
                    item for item in (swings_high if side == 1 else swings_low)
                    if item[1] <= known
                ]
                boundary = _nearest_target_boundary(side, midpoint, current_swings)
                fixed_target = midpoint + side * config.target_r * risk
                if boundary is not None and side * (boundary - midpoint) < config.min_target_r * risk:
                    continue
                target = (
                    boundary if boundary is not None
                    and side * (boundary - midpoint) < config.target_r * risk
                    else fixed_target
                )

                events.append({
                    'setup_id': f'{side}:{ob.Index.isoformat()}:{end.Index.isoformat()}',
                    'side': side,
                    'created_at': end.Index,
                    'ob_open_time': ob.Index,
                    'bottom': bottom,
                    'top': top,
                    'entry': float(midpoint),
                    'stop': float(stop),
                    'target': float(target),
                    'atr4h': float(end.atr),
                    'score': float(score),
                    'score_components': components,
                    'prior_touches': len(matching),
                    'displacement_atr': float(displacement),
                    'volume_ratio': float(impulse_volume_ratio),
                    'trend_aligned': trend_aligned,
                })
                published.add(setup_key)
    return events


def strong_level_signals(
    minutes: pd.DataFrame,
    config: StrongLevelRetestConfig,
) -> tuple[pd.DataFrame, list[dict]]:
    """Create resting orders at zone publication time, before any retest."""
    bars = four_hour_features(minutes)
    events = strong_level_events_from_bars(bars, config)
    signals = []
    for event in events:
        signals.append({
            'timestamp': event['created_at'],
            'side': event['side'],
            'reference': float(bars.loc[event['created_at'], 'close']),
            'stop': event['stop'],
            'atr': event['atr4h'],
            'limit_price': event['entry'],
            'limit_ttl_minutes': config.validity_hours * 60,
            'target_price': event['target'],
            'min_target_r': config.min_target_r,
            'min_stop_atr': 0.20,
            'max_stop_atr': 1.50,
            'score': event['score'],
            'setup': 'strong_ob_sr_first_retest',
            'setup_id': event['setup_id'],
            'order_block': [event['bottom'], event['top']],
            'evidence': {
                'score_components': event['score_components'],
                'prior_sr_touches': event['prior_touches'],
                'displacement_atr': event['displacement_atr'],
                'origin_volume_ratio': event['volume_ratio'],
                'trend_aligned': event['trend_aligned'],
                'armed_before_retest': True,
            },
        })
    signals.sort(key=lambda item: item['timestamp'])
    return bars, signals
