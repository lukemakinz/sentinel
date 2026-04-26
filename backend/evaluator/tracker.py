"""Signal lifecycle management — creation, MFE/MAE tracking, outcome."""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def create_signal(trade_context: dict, l2_decision: dict,
                  trade_params: dict = None, executed: bool = False) -> 'Signal':
    """Create Signal record for every L1 PASS — regardless of L2 verdict."""
    from .models import Signal

    ctx  = trade_context or {}
    l2   = l2_decision   or {}
    tp   = trade_params  or {}

    action = l2.get('action', 'NONE')
    shadow = (not executed) or (action == 'REJECT')

    agents = l2.get('agents_summary', {})
    agent_verdicts = {
        k: {'verdict': v.get('verdict'), 'confidence': v.get('confidence')}
        for k, v in agents.items()
    }

    entry = tp.get('entry_price') or ctx.get('entry_price')
    sl    = tp.get('stop_loss')
    tps   = tp.get('take_profits', [])
    tp1   = tps[0].get('level') if tps else None
    rr    = ((tp1 - entry) / (entry - sl)) if (tp1 and sl and entry and entry != sl) else None

    sig = Signal.objects.create(
        symbol=ctx.get('symbol', ''),
        direction=ctx.get('direction', ''),
        strategy=ctx.get('strategy', 'S1'),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tps[1].get('level') if len(tps) > 1 else None,
        r_value=tp.get('r_value'),
        rr_planned=round(rr, 2) if rr else None,
        gates_a_passed=ctx.get('gates_a', {}),
        gates_b_passed=ctx.get('gates_b', {}),
        gates_c_passed=ctx.get('gates_c', {}),
        regime=ctx.get('regime', ''),
        choppiness_index=ctx.get('choppiness_index'),
        htf_bias=ctx.get('direction', '').lower(),
        l2_action=action,
        l2_size_multiplier=l2.get('size_multiplier', 1.0),
        agent_verdicts=agent_verdicts,
        veto_reason=l2.get('veto_reason', ''),
        executed=executed,
        shadow=shadow,
        state='APPROVED' if action == 'APPROVE' else 'REJECTED',
    )

    logger.info(f"Signal created: {sig} shadow={shadow} executed={executed}")
    return sig


def update_mfe_mae(signal_id: int, current_price: float):
    """Update Max Favorable / Adverse Excursion per tick."""
    from .models import Signal
    try:
        sig = Signal.objects.get(pk=signal_id, state='MONITORING')
    except Signal.DoesNotExist:
        return

    if not sig.entry_price or not sig.r_value or sig.r_value == 0:
        return

    if sig.direction == 'LONG':
        current_r = (current_price - sig.entry_price) / sig.r_value
    else:
        current_r = (sig.entry_price - current_price) / sig.r_value

    update_fields = []
    if sig.mfe_r is None or current_r > sig.mfe_r:
        sig.mfe_r = round(current_r, 3)
        update_fields.append('mfe_r')
    if sig.mae_r is None or current_r < sig.mae_r:
        sig.mae_r = round(current_r, 3)
        update_fields.append('mae_r')

    if update_fields:
        sig.save(update_fields=update_fields)


def close_signal(signal_id: int, exit_price: float, exit_reason: str):
    """Record signal outcome on close."""
    from .models import Signal
    from django.utils import timezone

    try:
        sig = Signal.objects.get(pk=signal_id)
    except Signal.DoesNotExist:
        return

    sig.exit_price = exit_price
    sig.exit_reason = exit_reason
    sig.closed_at  = timezone.now()
    sig.state      = 'CLOSED'

    if sig.entry_price and sig.r_value and sig.r_value != 0:
        if sig.direction == 'LONG':
            sig.pnl_r = round((exit_price - sig.entry_price) / sig.r_value, 3)
        else:
            sig.pnl_r = round((sig.entry_price - exit_price) / sig.r_value, 3)

    if sig.created_at and sig.closed_at:
        sig.time_in_trade_min = int((sig.closed_at - sig.created_at).total_seconds() / 60)

    sig.compute_outcome()
    sig.save()
    logger.info(f"Signal {signal_id} closed: {sig.outcome} pnl={sig.pnl_r}R")
