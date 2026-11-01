"""Read-only KuCoin connectivity and protection preflight."""
from django.core.management.base import BaseCommand, CommandError

from executor.exchange_adapters import get_exchange_adapter
from executor.live_execution import (
    ACTIVE_INTENT_STATUSES,
    UNRESOLVED_INTENT_STATUSES,
)
from executor.models import ExchangeExecutionIntent
from executor.reconcile import protective_stop_mismatches, reconcile


class Command(BaseCommand):
    help = (
        'Read KuCoin futures account/order state and verify that every open '
        'position has an active reduce-only adverse stop. Never places orders.'
    )

    def handle(self, *args, **options):
        adapter = get_exchange_adapter()
        if not adapter.credentials_configured():
            raise CommandError('KuCoin credentials are not configured')

        checks = {
            'account': adapter.get_account_overview('USDT'),
            'positions': adapter.get_positions(),
            'orders': adapter.get_open_orders(),
            'stop_orders': adapter.get_stop_orders(),
        }
        failed = [name for name, result in checks.items() if not result.ok]
        if failed:
            details = ', '.join(
                f"{name}={checks[name].payload.get('code') or checks[name].payload.get('error') or 'error'}"
                for name in failed
            )
            raise CommandError(f'KuCoin read-only preflight failed: {details}')

        positions = adapter.normalize_positions(checks['positions'].payload)
        regular_orders = adapter.normalize_open_orders(checks['orders'].payload)
        stop_orders = adapter.normalize_stop_orders(checks['stop_orders'].payload)
        protection = protective_stop_mismatches(
            positions,
            stop_orders,
            stop_orders_ok=True,
        )
        active_intents = list(ExchangeExecutionIntent.objects.filter(
            status__in=ACTIVE_INTENT_STATUSES,
        ))
        unresolved_intents = [
            intent for intent in active_intents
            if intent.status in UNRESOLVED_INTENT_STATUSES
        ]
        pending_client_oids = {
            str(order.get('client_oid') or '').strip()
            for order in regular_orders
            if str(order.get('client_oid') or '').strip()
        }
        local_positions = [{
            'symbol': intent.symbol,
            'side': intent.side,
            'quantity': intent.submitted_quantity,
            'client_oid': intent.client_oid,
            'status': intent.status,
        } for intent in active_intents]
        reconciliation = reconcile(
            local_positions,
            positions,
            pending_client_oids=pending_client_oids,
        )

        self.stdout.write(
            'Read-only KuCoin state: '
            f'positions={len(positions)} regular_orders={len(regular_orders)} '
            f'stop_orders={len(stop_orders)}'
        )
        self.stdout.write(
            'Local execution intents: '
            f'active={len(active_intents)} unresolved={len(unresolved_intents)}'
        )

        failures = []
        if protection:
            failures.append('protection=' + ', '.join(
                f"{item['symbol']}:{item['issue']}" for item in protection
            ))
        if unresolved_intents:
            failures.append('unresolved_intents=' + ', '.join(
                f'{intent.client_oid}:{intent.status}'
                for intent in unresolved_intents[:5]
            ))
        if reconciliation:
            failures.append('reconciliation=' + ', '.join(
                f"{item['symbol']}:{item['issue']}" for item in reconciliation
            ))
        if failures:
            raise CommandError(
                'KuCoin safety preflight failed: ' + '; '.join(failures)
            )

        self.stdout.write(self.style.SUCCESS(
            'KuCoin read-only preflight OK; no order was submitted.'
        ))
