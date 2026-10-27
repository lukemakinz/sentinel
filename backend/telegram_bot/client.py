"""Minimal Telegram Bot API client (long polling); no extra dependency."""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
API = 'https://api.telegram.org/bot{token}/{method}'
MAX_MESSAGE = 4000


def configured() -> bool:
    return bool(getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
                and getattr(settings, 'TELEGRAM_CHAT_ID', ''))


def _call(method: str, http_timeout: float = 15, **payload):
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        return None
    response = requests.post(API.format(token=token, method=method),
                             json=payload, timeout=http_timeout)
    response.raise_for_status()
    return response.json().get('result')


def send_message(text: str, chat_id: str | None = None) -> bool:
    """Send to the operator chat; never raises (alerts must not break jobs)."""
    chat_id = chat_id or getattr(settings, 'TELEGRAM_CHAT_ID', '')
    if not chat_id or not getattr(settings, 'TELEGRAM_BOT_TOKEN', ''):
        logger.info('Telegram not configured; message dropped: %s', text[:80])
        return False
    try:
        for start in range(0, len(text), MAX_MESSAGE):
            _call('sendMessage', chat_id=chat_id, text=text[start:start + MAX_MESSAGE],
                  disable_web_page_preview=True)
        return True
    except requests.RequestException as exc:
        logger.warning('Telegram send failed: %s', exc)
        return False


def get_updates(offset: int | None, timeout: int = 25) -> list[dict]:
    # ``timeout`` here is Telegram's long-poll wait; HTTP waits a bit longer.
    return _call('getUpdates', http_timeout=timeout + 10, offset=offset,
                 timeout=timeout, allowed_updates=['message']) or []
