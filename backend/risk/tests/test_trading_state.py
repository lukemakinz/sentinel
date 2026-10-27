from unittest.mock import patch

from django.test import TestCase

from risk import trading_state as ts
from risk.models import RiskEvent


class TradingStateTests(TestCase):
    def test_system_only_escalates_and_cannot_lift_manual_halt(self):
        self.assertTrue(ts.escalate('CAUTION', 'vol'))
        self.assertFalse(ts.escalate('NORMAL', 'lower via escalate'))
        self.assertTrue(ts.escalate('HALT', 'recon', manual_unlock=True))
        self.assertFalse(ts.release('NORMAL', 'auto', by='system'))
        self.assertEqual(ts.current().state, 'HALT')
        self.assertTrue(ts.release('NORMAL', 'reviewed', by='operator_cli'))
        self.assertEqual(ts.current().state, 'NORMAL')
        self.assertEqual(RiskEvent.objects.filter(event_type='STATE_CHANGE').count(), 3)

    def test_multipliers_gate_entries(self):
        self.assertTrue(ts.allows_new_entries())
        ts.escalate('DEFENSIVE', 'x')
        self.assertEqual(ts.risk_multiplier(), 0.25)
        ts.escalate('CLOSE_ONLY', 'x')
        self.assertFalse(ts.allows_new_entries())

    @patch('risk.kill_switches.get_current_drawdown', return_value=0.0)
    @patch('telegram_bot.watchdog.feed_ages')
    def test_stale_feed_is_close_only_and_recovers_automatically(self, ages, _dd):
        ages.return_value = {'candles': 30, 'order_book': 900, 'agg_trades': 1}
        self.assertEqual(ts.evaluate_guards().state, 'CLOSE_ONLY')
        ages.return_value = {'candles': 30, 'order_book': 2, 'agg_trades': 1}
        self.assertEqual(ts.evaluate_guards().state, 'NORMAL')

    @patch('risk.kill_switches.get_current_drawdown', return_value=-12.0)
    @patch('telegram_bot.watchdog.feed_ages',
           return_value={'candles': 30, 'order_book': 2, 'agg_trades': 1})
    def test_drawdown_breach_is_manual_halt_even_after_feed_recovers(self, _ages, _dd):
        state = ts.evaluate_guards()
        self.assertEqual((state.state, state.manual_unlock), ('HALT', True))
        self.assertEqual(ts.evaluate_guards().state, 'HALT')
