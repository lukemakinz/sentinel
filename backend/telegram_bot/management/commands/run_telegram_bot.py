"""Long-running Telegram bot: operator commands, feed watchdog, daily summary.

Runs as its own process so feed alerts still fire when the ingester dies.
Only messages from TELEGRAM_CHAT_ID are executed.
"""
import logging
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from telegram_bot.client import get_updates, send_message
from telegram_bot.commands import daily_summary, handle
from telegram_bot.watchdog import FeedWatchdog

logger = logging.getLogger(__name__)


def process_update(update: dict, allowed_chat: str, reply) -> bool:
    """Execute one update if it comes from the operator chat."""
    message = update.get('message') or {}
    chat_id = str((message.get('chat') or {}).get('id', ''))
    text = message.get('text') or ''
    if not text:
        return False
    if not allowed_chat:
        # First-time setup: only tell the sender their id, run nothing.
        reply(f'Twoje chat_id: {chat_id}. Wpisz TELEGRAM_CHAT_ID={chat_id} do .env '
              'i zrestartuj bota.', chat_id)
        return False
    if chat_id != allowed_chat:
        logger.warning('Ignored Telegram message from chat %s', chat_id)
        return False
    reply(handle(text), chat_id)
    return True


class Command(BaseCommand):
    help = 'Run the Sentinel Telegram bot (commands + feed watchdog).'

    def handle(self, *args, **options):
        if not getattr(settings, 'TELEGRAM_BOT_TOKEN', ''):
            self.stderr.write('TELEGRAM_BOT_TOKEN missing in .env')
            return
        allowed = str(getattr(settings, 'TELEGRAM_CHAT_ID', '') or '')
        watchdog = FeedWatchdog(send_message)
        summary_hour = int(getattr(settings, 'TELEGRAM_DAILY_SUMMARY_HOUR_UTC', 7))
        last_summary_day = None
        next_watchdog = 0.0
        offset = None
        if allowed:
            send_message('🤖 Sentinel bot uruchomiony. /help')
        self.stdout.write('Telegram bot running')
        while True:
            try:
                for update in get_updates(offset, timeout=20):
                    offset = update['update_id'] + 1
                    process_update(update, allowed, lambda text, chat: send_message(text, chat))
                if allowed and time.monotonic() >= next_watchdog:
                    watchdog.check()
                    next_watchdog = time.monotonic() + 60
                now = timezone.now()
                if allowed and now.hour == summary_hour and last_summary_day != now.date():
                    send_message(daily_summary())
                    last_summary_day = now.date()
            except requests.RequestException as exc:
                logger.warning('Telegram polling error: %s', exc)
                time.sleep(10)
            except Exception as exc:  # keep the operator channel alive
                logger.error('Telegram bot loop error: %s', exc, exc_info=True)
                time.sleep(10)
