"""Feed freshness check, run from the bot process so it outlives the ingester."""
from django.conf import settings
from django.utils import timezone


def feed_ages() -> dict:
    """Seconds since the newest row of each live stream (None = no data)."""
    from ingester.models import AggTrade, Candle, OrderBookSnapshot

    now = timezone.now()
    ages = {}
    for name, model in (('candles', Candle), ('order_book', OrderBookSnapshot),
                        ('agg_trades', AggTrade)):
        latest = model.objects.order_by('-timestamp').values_list('timestamp', flat=True).first()
        ages[name] = None if latest is None else (now - latest).total_seconds()
    return ages


def stale_streams(ages: dict) -> list[str]:
    limit = getattr(settings, 'FEED_STALE_SECONDS', 300)
    # Candles close once a minute; allow one extra bar of slack.
    limits = {'candles': limit + 60, 'order_book': limit, 'agg_trades': limit}
    return [name for name, age in ages.items() if age is None or age > limits[name]]


class FeedWatchdog:
    """Alerts once when the feed goes stale and once when it recovers."""

    def __init__(self, send):
        self.send = send
        self.alerting = False

    def check(self) -> list[str]:
        stale = stale_streams(feed_ages())
        if stale and not self.alerting:
            self.send('🚨 Feed nieaktualny: ' + ', '.join(stale)
                      + '. Sprawdź ingester (analizy będą PASS na starych danych).')
            self.alerting = True
        elif not stale and self.alerting:
            self.send('✅ Feed znowu płynie.')
            self.alerting = False
        return stale
