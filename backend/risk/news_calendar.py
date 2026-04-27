"""News Calendar — blocks trading around high-impact macro events."""
from datetime import datetime, timezone, timedelta
from typing import Optional

BLACKOUT_BEFORE = timedelta(hours=2)
BLACKOUT_AFTER  = timedelta(hours=1)

# High-impact macro events — 2025 + 2026.
# Source: FOMC calendar + BLS CPI schedule + BLS NFP schedule (UTC times).
# TODO: Replace with live Trading Economics API before live trading.
_EVENTS_2026 = [
    # FOMC 2025
    {'name': 'FOMC', 'dt': '2025-01-29T19:00'},
    {'name': 'FOMC', 'dt': '2025-03-19T19:00'},
    {'name': 'FOMC', 'dt': '2025-05-07T19:00'},
    {'name': 'FOMC', 'dt': '2025-06-18T19:00'},
    {'name': 'FOMC', 'dt': '2025-07-30T19:00'},
    {'name': 'FOMC', 'dt': '2025-09-17T19:00'},
    {'name': 'FOMC', 'dt': '2025-11-07T19:00'},
    {'name': 'FOMC', 'dt': '2025-12-17T19:00'},
    # CPI 2025 (monthly, ~13th)
    {'name': 'CPI', 'dt': '2025-01-15T13:30'},
    {'name': 'CPI', 'dt': '2025-02-12T13:30'},
    {'name': 'CPI', 'dt': '2025-03-12T13:30'},
    {'name': 'CPI', 'dt': '2025-04-10T12:30'},
    {'name': 'CPI', 'dt': '2025-05-13T12:30'},
    {'name': 'CPI', 'dt': '2025-06-11T12:30'},
    {'name': 'CPI', 'dt': '2025-07-15T12:30'},
    {'name': 'CPI', 'dt': '2025-08-12T12:30'},
    {'name': 'CPI', 'dt': '2025-09-10T12:30'},
    {'name': 'CPI', 'dt': '2025-10-15T12:30'},
    {'name': 'CPI', 'dt': '2025-11-13T13:30'},
    {'name': 'CPI', 'dt': '2025-12-10T13:30'},
    # NFP 2025 (first Friday of month)
    {'name': 'NFP', 'dt': '2025-01-10T13:30'},
    {'name': 'NFP', 'dt': '2025-02-07T13:30'},
    {'name': 'NFP', 'dt': '2025-03-07T13:30'},
    {'name': 'NFP', 'dt': '2025-04-04T12:30'},
    {'name': 'NFP', 'dt': '2025-05-02T12:30'},
    {'name': 'NFP', 'dt': '2025-06-06T12:30'},
    {'name': 'NFP', 'dt': '2025-07-03T12:30'},
    {'name': 'NFP', 'dt': '2025-08-01T12:30'},
    {'name': 'NFP', 'dt': '2025-09-05T12:30'},
    {'name': 'NFP', 'dt': '2025-10-03T12:30'},
    {'name': 'NFP', 'dt': '2025-11-07T13:30'},
    {'name': 'NFP', 'dt': '2025-12-05T13:30'},
    # FOMC 2026
    {'name': 'FOMC', 'dt': '2026-01-29T19:00'},
    {'name': 'FOMC', 'dt': '2026-03-19T19:00'},
    {'name': 'FOMC', 'dt': '2026-05-07T19:00'},
    {'name': 'FOMC', 'dt': '2026-06-18T19:00'},
]

if False:  # archive — kept for reference
    _EVENTS_2026_ARCHIVE = [
    # FOMC meetings
    {'name': 'FOMC', 'dt': '2026-01-29T19:00'},
    {'name': 'FOMC', 'dt': '2026-03-19T19:00'},
    {'name': 'FOMC', 'dt': '2026-05-07T19:00'},
    {'name': 'FOMC', 'dt': '2026-06-18T19:00'},
    {'name': 'FOMC', 'dt': '2026-07-30T19:00'},
    {'name': 'FOMC', 'dt': '2026-09-17T19:00'},
    {'name': 'FOMC', 'dt': '2026-11-05T19:00'},
    {'name': 'FOMC', 'dt': '2026-12-17T19:00'},
    # CPI (US, monthly ~13th)
    {'name': 'CPI', 'dt': '2026-01-15T13:30'},
    {'name': 'CPI', 'dt': '2026-02-12T13:30'},
    {'name': 'CPI', 'dt': '2026-03-12T13:30'},
    {'name': 'CPI', 'dt': '2026-04-14T13:30'},
    {'name': 'CPI', 'dt': '2026-05-13T13:30'},
    {'name': 'CPI', 'dt': '2026-06-12T13:30'},
    # NFP (first Friday of month)
    {'name': 'NFP', 'dt': '2026-01-09T13:30'},
    {'name': 'NFP', 'dt': '2026-02-06T13:30'},
    {'name': 'NFP', 'dt': '2026-03-06T13:30'},
    {'name': 'NFP', 'dt': '2026-04-03T13:30'},
    {'name': 'NFP', 'dt': '2026-05-08T13:30'},
    {'name': 'NFP', 'dt': '2026-06-05T13:30'},
]


def _parse_events() -> list[dict]:
    events = []
    for e in _EVENTS_2026:
        dt = datetime.fromisoformat(e['dt']).replace(tzinfo=timezone.utc)
        events.append({'name': e['name'], 'datetime': dt})
    return events


def get_events_today(now: Optional[datetime] = None) -> list[dict]:
    """Return events whose blackout window overlaps with today."""
    if now is None:
        now = datetime.now(timezone.utc)
    # Check events within ±24h of now (generous window)
    return [
        e for e in _parse_events()
        if abs((e['datetime'] - now).total_seconds()) < 86400
    ]


def is_news_blackout(now: Optional[datetime] = None) -> bool:
    """True if current time is within blackout window of a high-impact event."""
    if now is None:
        now = datetime.now(timezone.utc)
    for event in get_events_today(now):
        event_dt = event['datetime']
        blackout_start = event_dt - BLACKOUT_BEFORE
        blackout_end   = event_dt + BLACKOUT_AFTER
        if blackout_start <= now <= blackout_end:
            return True
    return False


def update_news_calendar():
    """Log next upcoming event. Hardcoded for 2026 — future: CoinGecko API integration."""
    import logging
    log = logging.getLogger(__name__)
    nxt = get_next_event()
    if nxt:
        log.info(f"News calendar: next event = {nxt['name']} @ {nxt['datetime'].isoformat()}")
    else:
        log.info("News calendar: no upcoming events in 2026 list")


def get_next_event(now: Optional[datetime] = None) -> Optional[dict]:
    """Return the nearest upcoming event, or None."""
    if now is None:
        now = datetime.now(timezone.utc)
    upcoming = [e for e in _parse_events() if e['datetime'] > now]
    return min(upcoming, key=lambda e: e['datetime']) if upcoming else None
