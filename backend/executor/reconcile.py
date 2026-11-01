"""Compare what Sentinel believes it holds with what the exchange reports.

The exchange is not silently adopted as truth: any unexplained position, missing
position, side flip or size difference beyond tolerance halts trading until an
operator has looked at it.
"""
from __future__ import annotations


def reconcile(
    local: list[dict], exchange: list[dict], size_tolerance: float = 0.02,
    pending_client_oids: set[str] | None = None,
) -> list[dict]:
    """Mismatches between local intended and exchange positions (by symbol)."""
    mismatches = []
    pending_client_oids = pending_client_oids or set()
    local_by = {p['symbol']: p for p in local}
    exchange_by = {p['symbol']: p for p in exchange if abs(float(p.get('quantity_base') or 0)) > 0}
    for symbol in sorted(set(local_by) | set(exchange_by)):
        mine, theirs = local_by.get(symbol), exchange_by.get(symbol)
        if theirs is None:
            if mine.get('status') == 'CLOSING':
                continue
            if str(mine.get('client_oid') or '') in pending_client_oids:
                continue
            mismatches.append({'symbol': symbol, 'issue': 'MISSING_ON_EXCHANGE', 'local': mine})
            continue
        if mine is None:
            mismatches.append({'symbol': symbol, 'issue': 'UNKNOWN_ON_EXCHANGE', 'exchange': theirs})
            continue
        if mine['side'] != theirs['side']:
            mismatches.append({'symbol': symbol, 'issue': 'SIDE_MISMATCH',
                               'local': mine['side'], 'exchange': theirs['side']})
            continue
        want, have = abs(float(mine['quantity'])), abs(float(theirs['quantity_base']))
        if want <= 0 or abs(have - want) / want > size_tolerance:
            mismatches.append({'symbol': symbol, 'issue': 'SIZE_MISMATCH',
                               'local': want, 'exchange': have})
    return mismatches


def protective_stop_mismatches(
    exchange_positions: list[dict],
    stop_orders: list[dict],
    *,
    stop_orders_ok: bool,
) -> list[dict]:
    """Return positions without an active, reduce-only adverse stop.

    A stop that could add or reverse exposure is not protection.  The check is
    intentionally strict: if KuCoin's stop-order inventory cannot be read, all
    open exchange positions are treated as unverified and trading is halted.
    """
    positions = [
        pos for pos in exchange_positions
        if abs(float(pos.get('quantity_base') or 0.0)) > 0
    ]
    if not positions:
        return []
    if not stop_orders_ok:
        return [{
            'symbol': '*',
            'issue': 'STOP_ORDER_SYNC_FAILED',
            'open_positions': len(positions),
        }]

    mismatches = []
    for position in positions:
        symbol = position.get('symbol') or ''
        side = str(position.get('side') or '').upper()
        entry = float(position.get('entry_price') or position.get('mark_price') or 0.0)
        expected_order_side = 'SHORT' if side == 'LONG' else 'LONG'
        expected_direction = 'down' if side == 'LONG' else 'up'
        candidates = []
        for order in stop_orders:
            if order.get('symbol') != symbol:
                continue
            if str(order.get('side') or '').upper() != expected_order_side:
                continue
            if not bool(order.get('is_active', True)):
                continue
            if str(order.get('status') or 'active').lower() not in {'active', 'open', 'new'}:
                continue
            if not (bool(order.get('reduce_only')) or bool(order.get('close_order'))):
                continue
            if str(order.get('stop_direction') or '').lower() != expected_direction:
                continue
            stop_price = float(order.get('stop_price') or 0.0)
            if stop_price <= 0:
                continue
            if side == 'LONG' and entry > 0 and stop_price >= entry:
                continue
            if side == 'SHORT' and entry > 0 and stop_price <= entry:
                continue
            candidates.append(order)
        if not candidates:
            mismatches.append({
                'symbol': symbol,
                'issue': 'UNPROTECTED_ON_EXCHANGE',
                'side': side,
            })
    return mismatches


def local_intended_positions() -> list[dict]:
    from .live_execution import ACTIVE_INTENT_STATUSES
    from .models import ExchangeExecutionIntent

    return [
        {
            'symbol': intent.symbol,
            'side': intent.side,
            'quantity': intent.submitted_quantity,
            'client_oid': intent.client_oid,
            'status': intent.status,
        }
        for intent in ExchangeExecutionIntent.objects.filter(status__in=ACTIVE_INTENT_STATUSES)
    ]


def halt_on_mismatch(mismatches: list[dict]) -> bool:
    if not mismatches:
        return False
    from risk.models import RiskEvent
    from risk.trading_state import escalate

    RiskEvent.objects.create(event_type='RECONCILIATION', symbol='',
                             message=f'{len(mismatches)} exchange mismatch(es)',
                             metadata={'mismatches': mismatches})
    summary = ', '.join(f"{m['symbol']} {m['issue']}" for m in mismatches[:5])
    escalate('HALT', f'Exchange reconciliation: {summary}', manual_unlock=True)
    return True
