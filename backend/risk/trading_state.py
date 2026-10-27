"""Operating state machine: NORMAL -> CAUTION -> DEFENSIVE -> CLOSE_ONLY -> HALT.

Failure of any smart component may only reduce risk. The system escalates on
its own and de-escalates only states it set without ``manual_unlock``; HALT
after a reconciliation mismatch or a drawdown breach needs an operator.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import RiskEvent, TradingState

logger = logging.getLogger(__name__)

SEVERITY = {name: rank for rank, name in enumerate(TradingState.STATES)}
RISK_MULTIPLIER = {'NORMAL': 1.0, 'CAUTION': 0.5, 'DEFENSIVE': 0.25,
                   'CLOSE_ONLY': 0.0, 'HALT': 0.0}


def current() -> TradingState:
    state = TradingState.objects.order_by('pk').first()
    return state or TradingState.objects.create()


def allows_new_entries(state: TradingState | None = None) -> bool:
    return RISK_MULTIPLIER[(state or current()).state] > 0


def risk_multiplier(state: TradingState | None = None) -> float:
    return RISK_MULTIPLIER[(state or current()).state]


def _notify(text: str) -> None:
    try:
        from telegram_bot.client import send_message
        send_message(text)
    except Exception:  # alerting must never break a risk transition
        logger.warning('Trading state alert not sent: %s', text)


def _record(old: str, new: TradingState) -> None:
    RiskEvent.objects.create(
        event_type='STATE_CHANGE', symbol='',
        message=f'{old} -> {new.state}: {new.reason}'[:500],
        metadata={'from': old, 'to': new.state, 'manual_unlock': new.manual_unlock,
                  'by': new.set_by})
    icon = '🛑' if new.state in {'HALT', 'CLOSE_ONLY'} else '⚠️' if SEVERITY[new.state] else '✅'
    _notify(f'{icon} Stan handlu: {old} → {new.state}\n{new.reason}'
            + ('\nOdblokowanie tylko ręcznie (CLI).' if new.manual_unlock else ''))


def escalate(target: str, reason: str, by: str = 'system', manual_unlock: bool = False) -> bool:
    """Raise severity (or harden to manual unlock); never lowers it."""
    if target not in SEVERITY:
        raise ValueError(f'Unknown trading state: {target}')
    with transaction.atomic():
        state = current()
        old = state.state
        harden = target == old and manual_unlock and not state.manual_unlock
        if SEVERITY[target] < SEVERITY[old] or (target == old and not harden):
            return False
        state.state, state.reason, state.set_by = target, reason[:300], by
        state.manual_unlock = manual_unlock or (state.manual_unlock and target == old)
        state.since = timezone.now()
        state.save()
    _record(old, state)
    return True


def release(target: str, reason: str, by: str) -> bool:
    """Lower severity. The system may only release states it set automatically."""
    if target not in SEVERITY:
        raise ValueError(f'Unknown trading state: {target}')
    with transaction.atomic():
        state = current()
        old = state.state
        if SEVERITY[target] >= SEVERITY[old]:
            return False
        if state.manual_unlock and by == 'system':
            return False
        state.state, state.reason, state.set_by = target, reason[:300], by
        state.manual_unlock = False
        state.since = timezone.now()
        state.save()
    _record(old, state)
    return True


FEED_REASON = 'Feed stale: '


def evaluate_guards() -> TradingState:
    """Apply automatic rules; safe to call often from any process."""
    from telegram_bot.watchdog import feed_ages, stale_streams

    from .kill_switches import get_current_drawdown

    halt_dd = float(getattr(settings, 'TRADING_STATE_HALT_DRAWDOWN_PCT', 10.0))
    drawdown_pct = -get_current_drawdown()  # helper returns a negative percent
    if drawdown_pct >= halt_dd:
        escalate('HALT', f'Drawdown {drawdown_pct:.1f}% >= {halt_dd:.0f}%', manual_unlock=True)

    stale = stale_streams(feed_ages())
    state = current()
    if stale:
        escalate('CLOSE_ONLY', FEED_REASON + ', '.join(stale))
    elif state.state == 'CLOSE_ONLY' and state.reason.startswith(FEED_REASON):
        release('NORMAL', 'Feed recovered', by='system')
    return current()
