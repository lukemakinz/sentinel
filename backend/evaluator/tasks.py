"""Celery tasks for prospective counterfactual shadow evaluation."""
import logging

from celery import shared_task
from django.utils import timezone

from .shadow_resolver import replay_one_r_barrier


logger = logging.getLogger(__name__)


@shared_task(name='evaluator.resolve_s12ai_shadow')
def resolve_s12ai_shadow() -> dict:
    """Resolve expired S12AI decisions without treating them as real trades."""
    from ingester.models import Candle
    from .models import Signal

    queryset = Signal.objects.filter(
        strategy='S12AI', shadow=True,
        state__in=('APPROVED', 'REJECTED'),
        expires_at__lte=timezone.now(),
    ).order_by('created_at')
    resolved = skipped = 0
    for signal in queryset.iterator():
        if not signal.entry_price or not signal.stop_loss or not signal.expires_at:
            skipped += 1
            continue
        rows = list(Candle.objects.filter(
            symbol=signal.symbol,
            interval='1m',
            is_closed=True,
            timestamp__gte=signal.created_at,
            timestamp__lt=signal.expires_at,
        ).order_by('timestamp').values('timestamp', 'high', 'low', 'close'))
        payload = [{
            'timestamp': row['timestamp'],
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
        } for row in rows]
        outcome = replay_one_r_barrier(
            signal.direction,
            float(signal.entry_price),
            float(signal.stop_loss),
            signal.created_at,
            signal.expires_at,
            payload,
        )
        if outcome is None:
            skipped += 1
            continue
        signal.closed_at = outcome.closed_at
        signal.exit_price = outcome.exit_price
        signal.exit_reason = outcome.exit_reason
        signal.outcome = outcome.outcome
        signal.pnl_r = round(outcome.pnl_r, 4) if outcome.pnl_r is not None else None
        signal.mfe_r = round(outcome.mfe_r, 4) if outcome.mfe_r is not None else None
        signal.mae_r = round(outcome.mae_r, 4) if outcome.mae_r is not None else None
        signal.time_in_trade_min = (
            int((outcome.closed_at - outcome.filled_at).total_seconds() / 60)
            if outcome.filled_at else None
        )
        signal.state = 'EXPIRED' if outcome.outcome == 'EXPIRED' else 'CLOSED'
        signal.save(update_fields=[
            'closed_at', 'exit_price', 'exit_reason', 'outcome', 'pnl_r',
            'mfe_r', 'mae_r', 'time_in_trade_min', 'state',
        ])
        resolved += 1
    logger.info(f'S12AI shadow resolver: resolved={resolved} skipped={skipped}')
    return {'resolved': resolved, 'skipped': skipped}
