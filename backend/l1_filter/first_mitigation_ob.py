"""S10 candidate: first mitigation of a causal 1h order block.

An order block is published only after a later displacement candle has broken
an already-confirmed 1h swing.  The first subsequent visit consumes the block;
there is no fallback to an unrelated FVG or repeated entry on a persistent
zone.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib

from .compression_breakout_scalp import _confirmed_structure
from .scalp_strategy import ScalpConfig, resample_closed


@dataclass(frozen=True)
class FirstMitigationConfig:
    name: str = 'S10_fmob_central'
    displacement_atr: float = 1.50
    volume_multiple: float = 1.25
    validity_hours: int = 24
    target_r: float = 1.80
    entry_fraction: float = 0.50
    leverage: float = 20.0

    def execution(self) -> ScalpConfig:
        return ScalpConfig(
            name=self.name,
            minutes=5,
            target_r=self.target_r,
            partial_r=1.0,
            partial_fraction=0.0,
            trailing=True,
            trail_atr=0.8,
            max_hold_minutes=120,
            risk_fraction=0.0025,
            max_notional_equity=1.0,
            daily_loss_fraction=0.01,
            fee_bps=5.0,
            slippage_bps=2.0,
            min_reward_cost_ratio=4.0,
            leverage=self.leverage,
            max_margin_fraction=0.05,
            maker_fee_bps=2.0,
            limit_penetration_bps=2.0,
            margin_safety_reserve=0.01,
        )


def first_mitigation_variants() -> list[FirstMitigationConfig]:
    """Central configuration plus one-dimensional stability neighbours."""
    return [
        FirstMitigationConfig(),
        FirstMitigationConfig('S10_fmob_disp120', displacement_atr=1.20),
        FirstMitigationConfig('S10_fmob_disp180', displacement_atr=1.80),
        FirstMitigationConfig('S10_fmob_volume100', volume_multiple=1.00),
        FirstMitigationConfig('S10_fmob_volume150', volume_multiple=1.50),
        FirstMitigationConfig('S10_fmob_valid16h', validity_hours=16),
        FirstMitigationConfig('S10_fmob_valid32h', validity_hours=32),
        FirstMitigationConfig('S10_fmob_target150', target_r=1.50),
        FirstMitigationConfig('S10_fmob_target210', target_r=2.10),
        FirstMitigationConfig('S10_fmob_entry40', entry_fraction=0.40),
        FirstMitigationConfig('S10_fmob_entry60', entry_fraction=0.60),
    ]


def first_mitigation_features(minutes: pd.DataFrame) -> pd.DataFrame:
    bars = resample_closed(minutes, 5)
    bars['atr'] = talib.ATR(
        bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy(), 14)
    bars['volume_median20'] = bars.volume.shift().rolling(20).median()
    bars['prior_high2'] = bars.high.shift().rolling(2).max()
    bars['prior_low2'] = bars.low.shift().rolling(2).min()
    return bars


def _confirmed_swings(hourly: pd.DataFrame) -> tuple[list[tuple], list[tuple]]:
    highs, lows = hourly.high.to_numpy(), hourly.low.to_numpy()
    swing_highs, swing_lows = [], []
    for known in range(4, len(hourly)):
        pivot = known - 2
        if highs[pivot] == np.max(highs[pivot - 2:pivot + 3]):
            swing_highs.append((pivot, known, float(highs[pivot])))
        if lows[pivot] == np.min(lows[pivot - 2:pivot + 3]):
            swing_lows.append((pivot, known, float(lows[pivot])))
    return swing_highs, swing_lows


def causal_order_blocks(
    minutes: pd.DataFrame,
    config: FirstMitigationConfig,
) -> list[dict]:
    hourly = resample_closed(minutes, 60)
    hourly['atr'] = talib.ATR(
        hourly.high.to_numpy(), hourly.low.to_numpy(), hourly.close.to_numpy(), 14)
    hourly['volume_median20'] = hourly.volume.shift().rolling(20).median()
    swings_high, swings_low = _confirmed_swings(hourly)

    four_hour = resample_closed(minutes, 240)
    four_hour['bias'] = _confirmed_structure(four_hour)
    hourly['bias4h'] = four_hour.bias.reindex(hourly.index, method='ffill')

    rows = list(hourly.itertuples())
    events: list[dict] = []
    published: set[tuple] = set()
    for known in range(24, len(rows)):
        end = rows[known]
        if not np.isfinite(end.atr) or end.atr <= 0:
            continue
        for ob_i in range(max(0, known - 3), known):
            ob = rows[ob_i]
            for side in (1, -1):
                if side * (ob.close - ob.open) >= 0 or end.bias4h != side:
                    continue
                setup_id = (side, ob.Index)
                if setup_id in published:
                    continue
                prior_swings = (
                    [price for pivot, confirmed, price in swings_high
                     if pivot < ob_i and confirmed <= ob_i]
                    if side == 1 else
                    [price for pivot, confirmed, price in swings_low
                     if pivot < ob_i and confirmed <= ob_i]
                )
                if not prior_swings:
                    continue
                broken = max(prior_swings) if side == 1 else min(prior_swings)
                if side * (end.close - broken) < 0.05 * end.atr:
                    continue

                zone_bottom = float(ob.low if side == 1 else ob.open)
                zone_top = float(ob.open if side == 1 else ob.high)
                zone_width = zone_top - zone_bottom
                if not 0.20 * end.atr <= zone_width <= 0.90 * end.atr:
                    continue
                midpoint = (zone_bottom + zone_top) / 2
                if side * (end.close - midpoint) < config.displacement_atr * end.atr:
                    continue

                impulse = rows[ob_i + 1:known + 1]
                quality = False
                for candle in impulse:
                    candle_range = candle.high - candle.low
                    close_location = (
                        (candle.close - candle.low) / max(candle_range, 1e-12)
                        if side == 1 else
                        (candle.high - candle.close) / max(candle_range, 1e-12))
                    prior_volume = candle.volume_median20
                    if (side * (candle.close - candle.open) >= 0.8 * candle.atr
                            and close_location >= 0.75
                            and np.isfinite(prior_volume)
                            and candle.volume >= config.volume_multiple * prior_volume):
                        quality = True
                        break
                if not quality:
                    continue

                events.append({
                    'setup_id': f'{side}:{ob.Index.isoformat()}:{end.Index.isoformat()}',
                    'side': side,
                    'created_at': end.Index,
                    'ob_open_time': ob.Index,
                    'bottom': zone_bottom,
                    'top': zone_top,
                    'atr1h': float(end.atr),
                })
                published.add(setup_id)
    return events


def first_mitigation_signals(
    minutes: pd.DataFrame,
    config: FirstMitigationConfig,
) -> tuple[pd.DataFrame, list[dict]]:
    bars = first_mitigation_features(minutes)
    rows = list(bars.itertuples())
    index_positions = {timestamp: i for i, timestamp in enumerate(bars.index)}
    records: list[dict] = []

    for event in causal_order_blocks(minutes, config):
        side = event['side']
        created_i = int(bars.index.searchsorted(event['created_at']))
        expiry = event['created_at'] + pd.Timedelta(hours=config.validity_hours)
        end_i = int(bars.index.searchsorted(expiry, side='right'))
        touched_i = None
        for i in range(created_i, min(end_i, len(rows))):
            row = rows[i]
            visits = row.low <= event['top'] and row.high >= event['bottom']
            if not visits:
                continue
            # Any early touch consumes first mitigation, even if it occurs
            # before the two-hour minimum entry age.
            if row.Index < event['created_at'] + pd.Timedelta(hours=2):
                touched_i = -1
            else:
                touched_i = i
            break
        if touched_i is None or touched_i < 0:
            continue

        touch_extreme = rows[touched_i].low if side == 1 else rows[touched_i].high
        for i in range(touched_i, min(touched_i + 4, len(rows))):
            row = rows[i]
            touch_extreme = min(touch_extreme, row.low) if side == 1 else max(touch_extreme, row.high)
            local_hour = row.Index.hour + row.Index.minute / 60
            in_session = 7 <= local_hour < 11 or 13 <= local_hour < 17
            if not in_session:
                continue
            distal = event['bottom'] if side == 1 else event['top']
            if side * (row.close - distal) < -0.05 * event['atr1h']:
                break
            candle_range = row.high - row.low
            close_location = (
                (row.close - row.low) / max(candle_range, 1e-12)
                if side == 1 else
                (row.high - row.close) / max(candle_range, 1e-12))
            break_level = row.prior_high2 if side == 1 else row.prior_low2
            trigger = (
                side * (row.close - (event['bottom'] + event['top']) / 2) > 0
                and side * (row.close - break_level) > 0
                and side * (row.close - row.open) >= 0.5 * row.atr
                and close_location >= 0.70
                and np.isfinite(row.volume_median20)
                and row.volume >= row.volume_median20
            )
            if not trigger:
                continue

            body_low, body_high = sorted((float(row.open), float(row.close)))
            entry = body_low + config.entry_fraction * (body_high - body_low)
            stop = (min(event['bottom'], touch_extreme) - 0.10 * event['atr1h']
                    if side == 1 else
                    max(event['top'], touch_extreme) + 0.10 * event['atr1h'])
            risk = side * (entry - stop)
            stop_pct = risk / max(entry, 1e-12)
            if (risk > 0 and 0.0035 <= stop_pct <= 0.015
                    and 0.5 * event['atr1h'] <= risk <= 1.8 * event['atr1h']):
                records.append({
                    'timestamp': row.Index,
                    'side': side,
                    'reference': float(row.close),
                    'stop': float(stop),
                    # Execution validation and trailing use the frozen 1h ATR.
                    'atr': float(event['atr1h']),
                    'limit_price': float(entry),
                    'limit_ttl_minutes': 15,
                    'score': 0,
                    'setup': 'first_mitigation_order_block',
                    'setup_id': event['setup_id'],
                    'order_block': [event['bottom'], event['top']],
                })
            break

    records.sort(key=lambda x: x['timestamp'])
    return bars, records
