from django.db import models


class Candle(models.Model):
    """OHLCV candlestick data — TimescaleDB hypertable."""
    symbol = models.CharField(max_length=20, db_index=True)
    interval = models.CharField(max_length=5, db_index=True)  # 1m, 5m, 15m, 1h, 4h, 1d
    timestamp = models.DateTimeField(db_index=True)
    open = models.DecimalField(max_digits=20, decimal_places=8)
    high = models.DecimalField(max_digits=20, decimal_places=8)
    low = models.DecimalField(max_digits=20, decimal_places=8)
    close = models.DecimalField(max_digits=20, decimal_places=8)
    volume = models.DecimalField(max_digits=20, decimal_places=8)
    quote_volume = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    taker_buy_volume = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    taker_buy_quote_volume = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    num_trades = models.IntegerField(default=0)
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-timestamp']
        unique_together = ['symbol', 'interval', 'timestamp']
        indexes = [
            models.Index(fields=['symbol', 'interval', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.symbol} {self.interval} {self.timestamp}"


class FundingRate(models.Model):
    """Binance Futures funding rate."""
    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    funding_rate = models.DecimalField(max_digits=20, decimal_places=10)
    mark_price = models.DecimalField(max_digits=20, decimal_places=8)

    class Meta:
        ordering = ['-timestamp']
        unique_together = ['symbol', 'timestamp']

    def __str__(self):
        return f"{self.symbol} FR={self.funding_rate} @ {self.timestamp}"


class Liquidation(models.Model):
    """Individual liquidation events."""
    SIDE_CHOICES = [('BUY', 'Buy'), ('SELL', 'Sell')]

    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    side = models.CharField(max_length=4, choices=SIDE_CHOICES)
    price = models.DecimalField(max_digits=20, decimal_places=8)
    quantity = models.DecimalField(max_digits=20, decimal_places=8)
    usd_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['symbol', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.symbol} {self.side} liq {self.quantity} @ {self.price}"


class OpenInterest(models.Model):
    """Open interest snapshots."""
    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    open_interest = models.DecimalField(max_digits=20, decimal_places=8)
    open_interest_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    class Meta:
        ordering = ['-timestamp']
        unique_together = ['symbol', 'timestamp']

    def __str__(self):
        return f"{self.symbol} OI={self.open_interest} @ {self.timestamp}"


class LongShortRatio(models.Model):
    """Account long/short ratio from Binance."""
    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    long_account = models.DecimalField(max_digits=10, decimal_places=4)
    short_account = models.DecimalField(max_digits=10, decimal_places=4)
    long_short_ratio = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        ordering = ['-timestamp']
        unique_together = ['symbol', 'timestamp']

    def __str__(self):
        return f"{self.symbol} L/S={self.long_short_ratio} @ {self.timestamp}"


class TopTraderPosition(models.Model):
    """Top trader position ratio from Binance."""
    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    long_account = models.DecimalField(max_digits=10, decimal_places=4)
    short_account = models.DecimalField(max_digits=10, decimal_places=4)
    long_short_ratio = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        ordering = ['-timestamp']
        unique_together = ['symbol', 'timestamp']

    def __str__(self):
        return f"{self.symbol} TopTraders L/S={self.long_short_ratio} @ {self.timestamp}"


class MarketTicker(models.Model):
    """24hr ticker data for cross-asset analysis."""
    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    price = models.DecimalField(max_digits=20, decimal_places=8)
    price_change_pct = models.DecimalField(max_digits=10, decimal_places=4)
    volume_24h = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    market_cap = models.DecimalField(max_digits=30, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.symbol} ${self.price} ({self.price_change_pct}%)"


class WatchedPair(models.Model):
    """User-configured pairs to monitor and receive signals for."""
    symbol   = models.CharField(max_length=20, unique=True, db_index=True)
    active   = models.BooleanField(default=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['symbol']

    def __str__(self):
        return f"{self.symbol} ({'active' if self.active else 'paused'})"

    @classmethod
    def get_active_symbols(cls) -> list[str]:
        """Returns active symbols, falls back to settings.TRADING_PAIRS if none configured."""
        from django.conf import settings
        symbols = list(cls.objects.filter(active=True).values_list('symbol', flat=True))
        return symbols if symbols else list(settings.TRADING_PAIRS)


class AggTrade(models.Model):
    """Individual aggregate trades from Binance aggTrade stream."""
    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    price = models.DecimalField(max_digits=20, decimal_places=8)
    quantity = models.DecimalField(max_digits=20, decimal_places=8)
    usd_value = models.DecimalField(max_digits=20, decimal_places=2)
    is_buyer_maker = models.BooleanField()

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['symbol', '-timestamp']),
        ]

    def __str__(self):
        side = 'SELL' if self.is_buyer_maker else 'BUY'
        return f"{self.symbol} {side} ${self.usd_value} @ {self.timestamp}"


class WhaleThreshold(models.Model):
    """Rolling 95th-percentile trade size threshold per symbol (updated hourly)."""
    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    threshold_usd = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        get_latest_by = 'timestamp'
        indexes = [
            models.Index(fields=['symbol', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.symbol} whale threshold=${self.threshold_usd}"


class WhaleCVD(models.Model):
    """Cumulative Volume Delta for whale trades (usd_value >= WhaleThreshold)."""
    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    cumulative_delta = models.DecimalField(max_digits=30, decimal_places=2)

    class Meta:
        ordering = ['-timestamp']
        get_latest_by = 'timestamp'
        indexes = [
            models.Index(fields=['symbol', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.symbol} WhaleCVD={self.cumulative_delta} @ {self.timestamp}"


class RetailCVD(models.Model):
    """Cumulative Volume Delta for retail trades (usd_value < WhaleThreshold)."""
    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    cumulative_delta = models.DecimalField(max_digits=30, decimal_places=2)

    class Meta:
        ordering = ['-timestamp']
        get_latest_by = 'timestamp'
        indexes = [
            models.Index(fields=['symbol', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.symbol} RetailCVD={self.cumulative_delta} @ {self.timestamp}"
