"""Crash-safe, at-most-once live entry orchestration."""
from __future__ import annotations

from django.db import IntegrityError, transaction

from .exchange_adapters import ExchangeOrderResult
from .models import ExchangeExecutionIntent


ACTIVE_INTENT_STATUSES = ('PREPARED', 'ACCEPTED', 'UNCERTAIN', 'OPEN', 'CLOSING')
UNRESOLVED_INTENT_STATUSES = ('PREPARED', 'UNCERTAIN')


def _order_id(payload: dict) -> str:
    data = payload.get('data') if isinstance(payload, dict) else None
    return str((data or {}).get('orderId') or (data or {}).get('id') or '')


def _same_intent(intent: ExchangeExecutionIntent, submission: dict) -> bool:
    quantity = float(submission.get('quantity_base') or 0.0)
    return (
        intent.symbol == str(submission.get('symbol') or '')
        and intent.side == str(submission.get('side') or '').upper()
        and abs(float(intent.submitted_quantity) - quantity) <= 1e-12
        and abs(float(intent.stop_loss) - float(submission.get('stop_loss') or 0.0)) <= 1e-9
    )


def _recover_existing(adapter, intent: ExchangeExecutionIntent, submission: dict) -> ExchangeOrderResult:
    if not _same_intent(intent, submission):
        return ExchangeOrderResult(False, {
            'error': 'client_oid collision with different live intent',
            'client_oid': intent.client_oid,
            'manual_reconciliation_required': True,
        })
    if intent.status in {'ACCEPTED', 'OPEN', 'CLOSING'}:
        return ExchangeOrderResult(True, {
            'code': '200000',
            'data': {'orderId': intent.order_id, 'clientOid': intent.client_oid},
            'reused_execution_intent': True,
        })
    if intent.status in {'REJECTED', 'CANCELLED', 'CLOSED'}:
        return ExchangeOrderResult(False, {
            'error': f'execution intent is already {intent.status.lower()}',
            'client_oid': intent.client_oid,
            'prior_response': intent.response,
        })

    # PREPARED may mean the process died immediately before or after POST.
    # Looking up is safe; sending a second POST is not.
    lookup = adapter.get_order_by_client_oid(intent.client_oid)
    found = lookup.payload.get('data') if lookup.ok and isinstance(lookup.payload, dict) else None
    if isinstance(found, dict) and str(found.get('clientOid') or '') == intent.client_oid:
        intent.status = 'ACCEPTED'
        intent.order_id = str(found.get('orderId') or found.get('id') or '')
        intent.response = lookup.payload
        intent.save(update_fields=['status', 'order_id', 'response', 'updated_at'])
        return ExchangeOrderResult(True, {
            'code': '200000',
            'data': found,
            'recovered_from_execution_intent': True,
        })

    intent.status = 'UNCERTAIN'
    intent.response = {'lookup': lookup.payload}
    intent.save(update_fields=['status', 'response', 'updated_at'])
    return ExchangeOrderResult(False, {
        'error': 'prepared live intent has no provable exchange outcome',
        'client_oid': intent.client_oid,
        'recovery_lookup': lookup.payload,
        'manual_reconciliation_required': True,
    })


def submit_protected_entry(adapter, trade_params: dict, *, signal_ref: str = '') -> ExchangeOrderResult:
    """Persist a validated intent before the one and only exchange POST."""
    prepared = adapter.prepare_protected_order(trade_params)
    if not prepared.ok:
        return prepared
    submission = prepared.payload['submission']
    client_oid = str(submission['client_oid'])

    try:
        with transaction.atomic():
            intent, created = ExchangeExecutionIntent.objects.get_or_create(
                client_oid=client_oid,
                defaults={
                    'signal_ref': str(signal_ref or ''),
                    'symbol': str(submission['symbol']),
                    'side': str(submission['side']).upper(),
                    'strategy': str(submission.get('strategy') or ''),
                    'requested_quantity': float(trade_params.get('quantity') or 0.0),
                    'submitted_quantity': float(submission['quantity_base']),
                    'stop_loss': float(submission['stop_loss']),
                    'status': 'PREPARED',
                },
            )
    except IntegrityError:
        active = ExchangeExecutionIntent.objects.filter(
            symbol=str(submission['symbol']), status__in=ACTIVE_INTENT_STATUSES,
        ).first()
        return ExchangeOrderResult(False, {
            'error': 'another active execution intent already exists for symbol',
            'client_oid': client_oid,
            'existing_client_oid': active.client_oid if active else '',
        })
    if not created:
        # Do not hold a database transaction/lock during a network lookup.
        return _recover_existing(adapter, intent, submission)

    result = adapter.submit_prepared_protected_order(prepared.payload)
    intent = ExchangeExecutionIntent.objects.get(pk=intent.pk)
    intent.response = result.payload
    intent.order_id = _order_id(result.payload)
    if result.ok:
        intent.status = 'ACCEPTED'
    elif result.payload.get('submission_uncertain') or result.payload.get('manual_reconciliation_required'):
        intent.status = 'UNCERTAIN'
    else:
        intent.status = 'REJECTED'
    intent.save(update_fields=['status', 'order_id', 'response', 'updated_at'])
    return result
