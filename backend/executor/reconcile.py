"""Compare what Sentinel believes it holds with what the exchange reports.

The exchange is not silently adopted as truth: any unexplained position, missing
position, side flip or size difference beyond tolerance halts trading until an
operator has looked at it.
"""
from __future__ import annotations


def reconcile(local: list[dict], exchange: list[dict], size_tolerance: float = 0.02) -> list[dict]:
    """Mismatches between local intended and exchange positions (by symbol)."""
    mismatches = []
    local_by = {p['symbol']: p for p in local}
    exchange_by = {p['symbol']: p for p in exchange if abs(float(p.get('quantity_base') or 0)) > 0}
    for symbol in sorted(set(local_by) | set(exchange_by)):
        mine, theirs = local_by.get(symbol), exchange_by.get(symbol)
        if theirs is None:
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


def local_intended_positions() -> list[dict]:
    from .models import Position

    return [
        {'symbol': p.symbol, 'side': p.side, 'quantity': p.remaining_quantity or p.quantity}
        for p in Position.objects.filter(status='OPEN').exclude(source='exchange')
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
