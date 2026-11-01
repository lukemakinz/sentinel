from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from risk.trading_state import current


class RiskWatchdogCommandTests(TestCase):
    @override_settings(LIVE_TRADING_ENABLED=False)
    @patch('executor.tasks.sync_live_exchange_state')
    @patch('risk.management.commands.run_risk_watchdog.evaluate_guards')
    def test_exchange_is_not_contacted_when_live_is_disabled(self, guards, sync):
        guards.return_value = SimpleNamespace(state='NORMAL', reason='')

        call_command('run_risk_watchdog', '--once')

        sync.assert_not_called()

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.tasks.sync_live_exchange_state')
    @patch('risk.management.commands.run_risk_watchdog.evaluate_guards')
    def test_live_exchange_is_reconciled_by_watchdog(self, guards, sync):
        guards.return_value = current()
        sync.return_value = {'ok': True, 'payload': {}}

        call_command('run_risk_watchdog', '--once')

        sync.assert_called_once_with()

    @override_settings(LIVE_TRADING_ENABLED=True)
    @patch('executor.tasks.sync_live_exchange_state', side_effect=RuntimeError('boom'))
    @patch('risk.management.commands.run_risk_watchdog.evaluate_guards')
    def test_sync_crash_fails_closed(self, guards, _sync):
        guards.return_value = current()

        with self.assertRaises(RuntimeError):
            call_command('run_risk_watchdog', '--once')

        state = current()
        self.assertEqual(state.state, 'CLOSE_ONLY')
        self.assertTrue(state.manual_unlock)
