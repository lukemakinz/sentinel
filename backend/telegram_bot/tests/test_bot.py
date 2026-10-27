from unittest.mock import patch

from django.test import TestCase, override_settings

from l1_filter.models import SetupObservation
from risk.models import ControlFlag, system_paused
from telegram_bot import client
from telegram_bot.alerts import alert_new
from telegram_bot.commands import handle
from telegram_bot.management.commands.run_telegram_bot import process_update
from telegram_bot.watchdog import FeedWatchdog


def update(chat_id, text):
    return {'update_id': 1, 'message': {'chat': {'id': chat_id}, 'text': text}}


class TelegramAuthTests(TestCase):
    def test_only_operator_chat_runs_commands(self):
        replies = []
        reply = lambda text, chat: replies.append((chat, text))  # noqa: E731

        self.assertFalse(process_update(update(999, '/pauza'), '123', reply))
        self.assertFalse(system_paused())
        self.assertEqual(replies, [])

        self.assertTrue(process_update(update(123, '/pauza'), '123', reply))
        self.assertTrue(system_paused())

    def test_setup_mode_only_reveals_sender_chat_id(self):
        replies = []
        process_update(update(555, '/pauza'), '', lambda t, c: replies.append(t))

        self.assertIn('555', replies[0])
        self.assertFalse(system_paused())


class TelegramCommandTests(TestCase):
    def test_pause_blocks_cycles_and_resume_restores(self):
        from l1_filter.tasks import run_setup_search_cycle
        from l2_agents.tasks import run_auction_shadow_cycle

        handle('/pauza')
        self.assertEqual(run_setup_search_cycle.run(), {'paused': True})
        self.assertEqual(run_auction_shadow_cycle.run(), {'paused': True})
        handle('/wznow')
        self.assertFalse(ControlFlag.is_enabled('paused'))

    def test_unknown_command_returns_help_and_status_works(self):
        self.assertIn('/scan', handle('/foo'))
        self.assertIn('feed', handle('/status'))
        self.assertIn('AI dziś', handle('/koszt'))
        self.assertIn('Dziennik', handle('/raport'))


class TelegramDeliveryTests(TestCase):
    @override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_CHAT_ID='')
    def test_send_is_a_noop_without_configuration(self):
        self.assertFalse(client.send_message('x'))

    @override_settings(TELEGRAM_BOT_TOKEN='t', TELEGRAM_CHAT_ID='1')
    @patch('telegram_bot.client._call')
    def test_alert_new_sends_once_for_wanted_status(self, call):
        obs = SetupObservation.objects.create(
            key='k', kind='SETUP', symbol='XUSDT', side='LONG',
            event_time='2026-10-26T10:00:00Z', first_status='WAIT_RETEST',
            last_status='WAIT_RETEST', payload={'score': 6, 'next': 'limit 1'})
        self.assertEqual(alert_new([obs], {'WAIT_RETEST'}), 1)
        self.assertEqual(alert_new([obs], {'WAIT_RETEST'}), 0)
        self.assertEqual(call.call_count, 1)


class FeedWatchdogTests(TestCase):
    @patch('telegram_bot.watchdog.feed_ages')
    def test_alerts_once_then_recovery(self, ages):
        sent = []
        watchdog = FeedWatchdog(sent.append)
        ages.return_value = {'candles': 30, 'order_book': 900, 'agg_trades': 5}
        watchdog.check()
        watchdog.check()
        ages.return_value = {'candles': 30, 'order_book': 3, 'agg_trades': 5}
        watchdog.check()

        self.assertEqual(len(sent), 2)
        self.assertIn('order_book', sent[0])
        self.assertIn('znowu', sent[1])
