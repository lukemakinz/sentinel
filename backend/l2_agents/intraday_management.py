"""Frozen, deterministic intraday exit-policy counterfactuals.

These policies are research arms, not execution authority.  They consume the
same closed 1m candles as the canonical shadow resolver and use conservative
stop-first ordering whenever a stop and profit milestone share one candle.
"""
from __future__ import annotations

from datetime import datetime


POLICY_VERSION = 'auction-intraday-management-v1'
P1_POLICY = 'P1_STRUCTURAL'
P2_POLICY = 'P2_HYBRID'
POLICY_IDS = (P1_POLICY, P2_POLICY)

POLICY_DESCRIPTIONS = {
    P1_POLICY: {
        'tp1_r': 0.75,
        'tp1_fraction': 0.50,
        'final_target_r': 1.50,
        'post_tp1_stop': 'cost_breakeven_or_closed_1m_structure',
        'same_bar_policy': 'STOP_FIRST',
    },
    P2_POLICY: {
        'risk_cut_trigger_r': 0.50,
        'risk_cut_stop_r': -0.50,
        'tp1_r': 0.75,
        'tp1_fraction': 0.40,
        'tp2_r': 1.25,
        'tp2_fraction': 0.30,
        'runner_fraction': 0.30,
        'runner_trail_r': 0.50,
        'post_tp1_stop': 'cost_breakeven',
        'post_tp2_min_stop_r': 0.50,
        'same_bar_policy': 'STOP_FIRST',
    },
}


def _iso(value) -> str | None:
    return value.isoformat() if hasattr(value, 'isoformat') else None


def _direction_sign(direction: str) -> float:
    if direction == 'LONG':
        return 1.0
    if direction == 'SHORT':
        return -1.0
    raise ValueError(f'Unsupported direction: {direction}')


def _market_exit(raw_price: float, direction: str, slippage_bps: float) -> float:
    slip = float(slippage_bps) / 10_000.0
    return raw_price * (1.0 - slip if direction == 'LONG' else 1.0 + slip)


def _level(entry: float, risk: float, direction: str, r_multiple: float) -> float:
    return entry + _direction_sign(direction) * risk * float(r_multiple)


def _favorable_r(row: dict, entry: float, risk: float, direction: str) -> float:
    if direction == 'LONG':
        return (float(row['high']) - entry) / risk
    return (entry - float(row['low'])) / risk


def _adverse_r(row: dict, entry: float, risk: float, direction: str) -> float:
    if direction == 'LONG':
        return (float(row['low']) - entry) / risk
    return (entry - float(row['high'])) / risk


def _touched(row: dict, level: float, direction: str, *, favorable: bool) -> bool:
    if direction == 'LONG':
        return float(row['high'] if favorable else row['low']) >= level \
            if favorable else float(row['low']) <= level
    return float(row['low']) <= level if favorable else float(row['high']) >= level


def simulate_intraday_policy(
    *,
    direction: str,
    entry: float,
    initial_stop: float,
    rows: list[dict],
    costs: dict,
    policy_id: str,
    opened_at: datetime | None = None,
) -> dict:
    """Score one frozen management policy on a completed post-entry window.

    Stop changes become active on the *next* candle.  Profit limit fills use
    maker fees; stops, trailing exits, time exits and UTC-day flattening use
    taker fees plus adverse slippage.  All fractions refer to original size.
    """
    if policy_id not in POLICY_IDS:
        raise ValueError(f'Unknown intraday management policy: {policy_id}')
    entry = float(entry)
    initial_stop = float(initial_stop)
    risk = abs(entry - initial_stop)
    if risk <= 0:
        return {'complete': False, 'reason': 'invalid_geometry',
                'policy_id': policy_id, 'version': POLICY_VERSION}
    if not rows:
        return {'complete': False, 'reason': 'no_post_entry_rows',
                'policy_id': policy_id, 'version': POLICY_VERSION}

    opened_at = opened_at or rows[0].get('timestamp')
    opened_day = getattr(opened_at, 'date', lambda: None)()
    active_rows = []
    flattened_at_utc_day_end = False
    for row in rows:
        stamp = row.get('timestamp')
        if opened_day is not None and stamp is not None and stamp.date() != opened_day:
            flattened_at_utc_day_end = True
            break
        active_rows.append(row)
    if not active_rows:
        return {'complete': False, 'reason': 'no_same_day_rows',
                'policy_id': policy_id, 'version': POLICY_VERSION}

    config = POLICY_DESCRIPTIONS[policy_id]
    entry_fee_bps = float(costs.get('entry_taker_fee_bps', 5.0))
    maker_fee_bps = float(costs.get('target_maker_fee_bps', 2.0))
    taker_fee_bps = float(costs.get('stop_taker_fee_bps', 5.0))
    slippage_bps = float(costs.get('market_slippage_bps', 5.0))
    entry_fee_r = entry * entry_fee_bps / 10_000.0 / risk
    # This level covers a full-size entry fee, taker exit fee and expected
    # adverse exit slippage.  It is intentionally conservative after a partial.
    be_delta = entry * (entry_fee_bps + taker_fee_bps + slippage_bps) / 10_000.0
    cost_be = entry + _direction_sign(direction) * be_delta

    remaining = 1.0
    realized_gross_r = 0.0
    exit_fee_r = 0.0
    effective_stop = initial_stop
    mfe_r = 0.0
    mae_r = 0.0
    tp1_hit = False
    tp2_hit = False
    stop_moves: list[dict] = []
    partials: list[dict] = []
    recent_rows: list[dict] = []

    def better_stop(candidate: float) -> bool:
        return candidate > effective_stop if direction == 'LONG' else candidate < effective_stop

    def move_stop(candidate: float, reason: str, after_row: dict) -> None:
        nonlocal effective_stop
        if not better_stop(candidate):
            return
        old = effective_stop
        effective_stop = candidate
        stop_moves.append({
            'active_after': _iso(after_row.get('timestamp')),
            'from': round(old, 8), 'to': round(candidate, 8), 'reason': reason,
        })

    def realize(fraction: float, raw_price: float, *, market: bool,
                label: str, row: dict) -> None:
        nonlocal remaining, realized_gross_r, exit_fee_r
        fraction = min(max(float(fraction), 0.0), remaining)
        if fraction <= 0:
            return
        fill = _market_exit(raw_price, direction, slippage_bps) if market else raw_price
        unit_gross = _direction_sign(direction) * (fill - entry) / risk
        fee_bps = taker_fee_bps if market else maker_fee_bps
        realized_gross_r += fraction * unit_gross
        exit_fee_r += fraction * fill * fee_bps / 10_000.0 / risk
        remaining = max(0.0, remaining - fraction)
        partials.append({
            'timestamp': _iso(row.get('timestamp')), 'label': label,
            'fraction': round(fraction, 6), 'fill_price': round(fill, 8),
            'gross_r_contribution': round(fraction * unit_gross, 6),
        })

    def result(reason: str, row: dict, raw_price: float, *, market: bool) -> dict:
        if remaining > 0:
            realize(remaining, raw_price, market=market, label=reason, row=row)
        gross = realized_gross_r
        net = gross - entry_fee_r - exit_fee_r
        return {
            'version': POLICY_VERSION,
            'policy_id': policy_id,
            'complete': True,
            'exit_reason': reason,
            'closed_at': _iso(row.get('timestamp')),
            'gross_r': round(gross, 6),
            'fee_r': round(entry_fee_r + exit_fee_r, 6),
            'net_r': round(net, 6),
            'mfe_r': round(mfe_r, 6),
            'mae_r': round(mae_r, 6),
            'tp1_hit': tp1_hit,
            'tp2_hit': tp2_hit,
            'partials': partials,
            'stop_moves': stop_moves,
            'final_stop': round(effective_stop, 8),
            'flattened_at_utc_day_end': flattened_at_utc_day_end,
        }

    for row in active_rows:
        recent_rows.append(row)
        favorable = _favorable_r(row, entry, risk, direction)
        adverse = _adverse_r(row, entry, risk, direction)
        mfe_r, mae_r = max(mfe_r, favorable), min(mae_r, adverse)

        # Conservative intrabar ordering: the stop active at candle open wins.
        if _touched(row, effective_stop, direction, favorable=False):
            label = 'STOP'
            if tp2_hit:
                label = 'TRAILING_STOP'
            elif tp1_hit:
                label = 'PROTECTED_STOP'
            return result(label, row, effective_stop, market=True)

        pending_moves: list[tuple[float, str]] = []
        if policy_id == P1_POLICY:
            tp1 = _level(entry, risk, direction, config['tp1_r'])
            final_target = _level(entry, risk, direction, config['final_target_r'])
            if not tp1_hit and _touched(row, tp1, direction, favorable=True):
                realize(config['tp1_fraction'], tp1, market=False, label='TP1', row=row)
                tp1_hit = True
                structure_rows = recent_rows[-3:]
                structure = (
                    min(float(value['low']) for value in structure_rows)
                    if direction == 'LONG'
                    else max(float(value['high']) for value in structure_rows)
                )
                candidate = max(cost_be, structure) if direction == 'LONG' else min(cost_be, structure)
                pending_moves.append((candidate, 'TP1_COST_BE_OR_1M_STRUCTURE'))
            if _touched(row, final_target, direction, favorable=True):
                return result('TARGET', row, final_target, market=False)
        else:
            tp1 = _level(entry, risk, direction, config['tp1_r'])
            tp2 = _level(entry, risk, direction, config['tp2_r'])
            if not tp1_hit and _touched(row, tp1, direction, favorable=True):
                realize(config['tp1_fraction'], tp1, market=False, label='TP1', row=row)
                tp1_hit = True
            if not tp2_hit and _touched(row, tp2, direction, favorable=True):
                realize(config['tp2_fraction'], tp2, market=False, label='TP2', row=row)
                tp2_hit = True

            if favorable >= config['risk_cut_trigger_r']:
                pending_moves.append((
                    _level(entry, risk, direction, config['risk_cut_stop_r']),
                    'MFE_0_5R_RISK_CUT',
                ))
            if tp1_hit:
                pending_moves.append((cost_be, 'TP1_COST_BREAKEVEN'))
            if tp2_hit:
                lock_r = max(
                    config['post_tp2_min_stop_r'],
                    mfe_r - config['runner_trail_r'],
                )
                pending_moves.append((
                    _level(entry, risk, direction, lock_r),
                    'TP2_RUNNER_TRAIL',
                ))

        # A stop created from this candle is active only from the next candle.
        for candidate, reason in pending_moves:
            close = float(row['close'])
            already_beyond_new_stop = (
                close <= candidate if direction == 'LONG' else close >= candidate
            )
            if already_beyond_new_stop and better_stop(candidate):
                # A stop cannot be installed on the protected side of the
                # current market.  Flatten now rather than pretending the next
                # candle can fill an impossible stop price.
                return result(f'{reason}_MARKET_CLOSE', row, close, market=True)
            move_stop(candidate, reason, row)

    final_row = active_rows[-1]
    reason = 'EOD_FLAT' if flattened_at_utc_day_end else 'TIME'
    return result(reason, final_row, float(final_row['close']), market=True)
