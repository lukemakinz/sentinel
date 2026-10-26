"""Causal state machine for fresh-level sweep/reclaim market entries."""
from __future__ import annotations

from collections import Counter

import pandas as pd


def _overlaps_zone(row, bottom: float, top: float) -> bool:
    return row.high >= bottom and row.low <= top


def _first_contact(minutes: pd.DataFrame, future: pd.DataFrame, side: int,
                   bottom: float, top: float):
    """Return first overlap or adverse gap through the whole zone."""
    if future.empty:
        return None
    first = future.index[0]
    prior = minutes.loc[minutes.index < first]
    previous_close = float(prior.iloc[-1].close) if not prior.empty else None
    for row in future.itertuples():
        gap_through = False
        if previous_close is not None:
            gap_through = (
                previous_close > top and row.open < bottom if side == 1
                else previous_close < bottom and row.open > top
            )
        if _overlaps_zone(row, bottom, top) or gap_through:
            return row.Index
        previous_close = float(row.close)
    return None


def _zones_merge(left: dict, right: dict, midpoint_atr: float) -> bool:
    left_bottom, left_top = left['order_block']
    right_bottom, right_top = right['order_block']
    intersects = max(left_bottom, right_bottom) <= min(left_top, right_top)
    midpoint_distance = abs(
        0.5 * (left_bottom + left_top) - 0.5 * (right_bottom + right_top))
    tolerance = midpoint_atr * min(left['atr'], right['atr'])
    return intersects or midpoint_distance <= tolerance


def stress_target_price(
    side: int,
    entry_open: float,
    stop_trigger: float,
    fee_bps: float,
    slippage_bps: float,
    target_net_r: float,
) -> tuple[float, float, float]:
    """Return target trigger, stress entry fill and stress unit loss."""
    fee = fee_bps / 10000.0
    slip = slippage_bps / 10000.0
    entry = entry_open * (1 + side * slip)
    stop_fill = stop_trigger * (1 - side * slip)
    unit_loss = side * (entry - stop_fill) + fee * entry + fee * stop_fill
    if unit_loss <= 0:
        raise ValueError('Stop does not create a positive stress loss')
    target_fill = (
        target_net_r * unit_loss + side * entry + fee * entry
    ) / (side - fee)
    target_trigger = target_fill / (1 - side * slip)
    return float(target_trigger), float(entry), float(unit_loss)


def _premitigation_status(minutes: pd.DataFrame, level: dict, departure_atr: float) -> str | None:
    bottom, top = level['order_block']
    side, atr = level['side'], level['atr']
    path = minutes.loc[
        (minutes.index >= level['ob_close_time'])
        & (minutes.index < level['created_at'])
    ]
    departed = False
    for row in path.itertuples():
        if not departed:
            departed = (
                row.high >= top + departure_atr * atr if side == 1
                else row.low <= bottom - departure_atr * atr
            )
            # The departure minute may naturally still span the origin zone;
            # only a later return counts as pre-mitigation.
            continue
        if _overlaps_zone(row, bottom, top):
            return 'PREMITIGATED'
    return None if departed else 'NO_DEPARTURE'


def materialize_sweep_reclaims(
    minutes: pd.DataFrame,
    armed_levels: list[dict],
    config,
    *,
    stress_fee_bps: float = 8.0,
    stress_slippage_bps: float = 5.0,
) -> tuple[list[dict], dict]:
    """Turn immutable levels into next-open market signals and an audit trail.

    Raw triggers are independent of the reporting cost scenario.  Eligibility,
    sizing stop geometry and target are frozen against the stress assumptions.
    """
    levels = sorted(
        (dict(item) for item in armed_levels),
        key=lambda item: (item['created_at'], -item.get('score', 0), item['setup_id']),
    )
    representatives: list[dict] = []
    audit: list[dict] = []

    for level in levels:
        status = _premitigation_status(minutes, level, config.departure_atr)
        if status is not None:
            audit.append({'setup_id': level['setup_id'], 'status': status})
            continue
        alias = next((
            old for old in representatives
            if old['side'] == level['side']
            and level['created_at'] < old['created_at'] + pd.Timedelta(
                minutes=old['limit_ttl_minutes'])
            and _zones_merge(old, level, config.merge_midpoint_atr)
        ), None)
        if alias is not None:
            audit.append({
                'setup_id': level['setup_id'], 'status': 'MERGED_ALIAS',
                'level_id': alias['setup_id'],
            })
            continue
        representatives.append(level)

    signals: list[dict] = []
    for level in representatives:
        created = level['created_at']
        expires = created + pd.Timedelta(minutes=level['limit_ttl_minutes'])
        bottom, top = level['order_block']
        side, atr = level['side'], level['atr']
        future = minutes.loc[(minutes.index >= created) & (minutes.index < expires)]
        contact = _first_contact(minutes, future, side, bottom, top)
        if contact is None:
            audit.append({'setup_id': level['setup_id'], 'status': 'EXPIRED'})
            continue
        deadline = min(expires, contact + pd.Timedelta(minutes=config.reclaim_minutes))
        episode = minutes.loc[(minutes.index >= contact) & (minutes.index < deadline)]
        swept = False
        sweep_extreme = top if side == 1 else bottom
        outcome = 'NO_RECLAIM_CONSUMED'
        trigger = None

        for row in episode.itertuples():
            penetration = (
                (bottom - row.low) / atr if side == 1
                else (row.high - top) / atr
            )
            sweep_extreme = (
                min(sweep_extreme, row.low) if side == 1
                else max(sweep_extreme, row.high)
            )
            if penetration > config.max_sweep_atr:
                outcome = 'INVALIDATED'
                break
            if penetration >= config.min_sweep_atr:
                swept = True

            close_time = row.Index + pd.Timedelta(minutes=1)
            if close_time.minute % 5 != 0:
                continue
            proximal = top if side == 1 else bottom
            distal = bottom if side == 1 else top
            reclaimed = side * (row.close - proximal) > 0
            if reclaimed and (swept or not config.require_distal_sweep):
                trigger = (close_time, float(row.close), float(sweep_extreme))
                outcome = 'TRIGGERED'
                break
            if config.require_distal_sweep and not swept and reclaimed:
                outcome = 'SHALLOW_TOUCH_CONSUMED'
                break
            if side * (row.close - distal) < 0:
                outcome = 'INVALIDATED'
                break

        if trigger is None:
            audit.append({
                'setup_id': level['setup_id'], 'status': outcome,
                'contact_at': str(contact),
            })
            continue

        entry_time, reclaim_close, sweep_extreme = trigger
        if entry_time not in minutes.index:
            audit.append({'setup_id': level['setup_id'], 'status': 'ENTRY_DATA_MISSING'})
            continue
        entry_open = float(minutes.loc[entry_time, 'open'])
        proximal = top if side == 1 else bottom
        if side * (entry_open - proximal) <= 0:
            audit.append({'setup_id': level['setup_id'], 'status': 'ENTRY_LOST_RECLAIM'})
            continue
        if side * (entry_open - reclaim_close) > config.max_entry_chase_atr * atr:
            audit.append({'setup_id': level['setup_id'], 'status': 'ENTRY_CHASED'})
            continue

        stop = (
            min(bottom, sweep_extreme) - config.stop_buffer_atr * atr
            if side == 1 else
            max(top, sweep_extreme) + config.stop_buffer_atr * atr
        )
        try:
            target, stress_entry, unit_loss = stress_target_price(
                side, entry_open, stop, stress_fee_bps, stress_slippage_bps,
                config.target_net_r)
        except ValueError:
            audit.append({'setup_id': level['setup_id'], 'status': 'INVALID_STOP'})
            continue
        stop_width = side * (stress_entry - stop) / atr
        if not config.min_stop_atr <= stop_width <= config.max_stop_atr:
            audit.append({'setup_id': level['setup_id'], 'status': 'STOP_WIDTH_REJECTED'})
            continue
        boundary = level.get('target_boundary')
        causal_boundary = (
            boundary if boundary is not None
            and side * (boundary - stress_entry) > 0 else None
        )
        if causal_boundary is not None:
            if side * (causal_boundary - target) <= 0:
                audit.append({'setup_id': level['setup_id'], 'status': 'TARGET_BLOCKED'})
                continue

        evidence = dict(level.get('evidence') or {})
        evidence.update({
            'level_created_at': str(created),
            'first_contact_at': str(contact),
            'reclaim_closed_at': str(entry_time),
            'entry_rule': 'next_1m_open_market',
            'sweep_extreme': float(sweep_extreme),
            'stress_unit_loss': float(unit_loss),
            'stress_target_net_r': config.target_net_r,
        })
        signals.append({
            'timestamp': entry_time,
            'side': side,
            'reference': entry_open,
            'stop': float(stop),
            'atr': float(atr),
            'target_price': float(target),
            'target_boundary': causal_boundary,
            'min_target_r': 0.0,
            'min_stop_atr': config.min_stop_atr,
            'max_stop_atr': config.max_stop_atr,
            'score': float(level.get('score', 0)),
            'setup': config.name,
            'setup_id': level['setup_id'],
            'evidence': evidence,
        })
        audit.append({
            'setup_id': level['setup_id'], 'status': 'TRIGGERED',
            'contact_at': str(contact), 'entry_at': str(entry_time),
        })

    signals.sort(key=lambda item: (item['timestamp'], -item['score'], item['setup_id']))
    directions = {}
    for signal in signals:
        directions.setdefault(signal['timestamp'], set()).add(signal['side'])
    conflicts = {timestamp for timestamp, sides in directions.items() if len(sides) > 1}
    if conflicts:
        conflicted_ids = {
            signal['setup_id'] for signal in signals if signal['timestamp'] in conflicts
        }
        signals = [signal for signal in signals if signal['timestamp'] not in conflicts]
        for row in audit:
            if row['setup_id'] in conflicted_ids and row['status'] == 'TRIGGERED':
                row['status'] = 'OPPOSITE_CONFLICT_CONSUMED'
    counts = Counter(item['status'] for item in audit)
    return signals, {'counts': dict(counts), 'levels': audit}
