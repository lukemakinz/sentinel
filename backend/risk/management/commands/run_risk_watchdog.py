"""Run feed, drawdown and optional live-exchange guards independently."""
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from risk.trading_state import current, escalate, evaluate_guards


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Continuously enforce feed/drawdown guards and, when live trading is '
        'enabled, reconcile protected exchange state.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=float, default=60.0)
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        interval = max(float(options['interval']), 5.0)
        while True:
            try:
                state = evaluate_guards()
                if settings.LIVE_TRADING_ENABLED:
                    try:
                        from executor.tasks import sync_live_exchange_state
                        sync_result = sync_live_exchange_state()
                    except Exception as exc:
                        escalate(
                            'CLOSE_ONLY',
                            f'Exchange sync crashed: {type(exc).__name__}',
                            by='risk_watchdog',
                            manual_unlock=True,
                        )
                        raise
                    if not sync_result.get('ok'):
                        payload = sync_result.get('payload') or {}
                        logger.warning(
                            'Live exchange sync incomplete: critical=%s '
                            'overview_ok=%s positions_ok=%s orders_ok=%s '
                            'fills_ok=%s closed_orders_ok=%s',
                            payload.get('critical_read_failures'),
                            payload.get('overview_ok'),
                            payload.get('positions_ok'),
                            payload.get('orders_ok'),
                            payload.get('fills_ok'),
                            payload.get('closed_orders_ok'),
                        )
                    state = current()
                self.stdout.write(f'{state.state}: {state.reason}')
            except Exception as exc:
                logger.exception('Risk watchdog evaluation failed: %s', exc)
                if options['once']:
                    raise
            if options['once']:
                return
            time.sleep(interval)
