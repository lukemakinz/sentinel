"""Show or change the trading state. The only place a manual HALT is lifted."""
from django.core.management.base import BaseCommand, CommandError

from risk.models import TradingState
from risk.trading_state import current, escalate, release


class Command(BaseCommand):
    help = 'Show the trading state; --set raises it, --release lowers it (operator only).'

    def add_arguments(self, parser):
        parser.add_argument('--set', choices=TradingState.STATES, help='Raise to this state.')
        parser.add_argument('--release', choices=TradingState.STATES,
                            help='Lower to this state (e.g. NORMAL) after review.')
        parser.add_argument('--reason', default='', help='Required with --set/--release.')

    def handle(self, *args, **options):
        if (options['set'] or options['release']) and not options['reason'].strip():
            raise CommandError('--reason is required')
        if options['set']:
            changed = escalate(options['set'], options['reason'], by='operator_cli', manual_unlock=True)
            self.stdout.write('raised' if changed else 'unchanged (not higher than current)')
        if options['release']:
            changed = release(options['release'], options['reason'], by='operator_cli')
            self.stdout.write('released' if changed else 'unchanged (not lower than current)')
        state = current()
        lock = ' [manual unlock]' if state.manual_unlock else ''
        self.stdout.write(f'{state.state}{lock} since {state.since:%Y-%m-%d %H:%M} UTC '
                          f'by {state.set_by or "-"}: {state.reason or "-"}')
