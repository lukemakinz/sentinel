from django.db import models


class RiskState(models.Model):
    """Current risk management state."""
    updated_at = models.DateTimeField(auto_now=True)
    daily_pnl = models.FloatField(default=0)
    weekly_pnl = models.FloatField(default=0)
    consecutive_losses = models.IntegerField(default=0)
    is_daily_stopped = models.BooleanField(default=False)
    is_weekly_stopped = models.BooleanField(default=False)
    position_size_multiplier = models.FloatField(default=1.0)  # Reduced after losses
    current_open_positions = models.IntegerField(default=0)

    class Meta:
        verbose_name = 'Risk State'
        verbose_name_plural = 'Risk State'

    def __str__(self):
        return f"Risk State: PnL={self.daily_pnl:+.2f}% | Losses={self.consecutive_losses}"


class RiskEvent(models.Model):
    """Log of risk events (kill switch activations, etc.)."""
    EVENT_TYPES = [
        ('DAILY_STOP', 'Daily Stop Activated'),
        ('WEEKLY_STOP', 'Weekly Stop Activated'),
        ('LOSS_STREAK', 'Consecutive Loss Reduction'),
        ('VOLATILITY_SPIKE', 'Volatility Spike'),
        ('FUNDING_BLOCK', 'Funding Rate Block'),
        ('MAX_POSITIONS', 'Max Positions Reached'),
        ('POSITION_OPENED', 'Position Opened'),
        ('POSITION_CLOSED', 'Position Closed'),
    ]

    timestamp = models.DateTimeField(auto_now_add=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    symbol = models.CharField(max_length=20, blank=True)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.event_type} | {self.symbol} | {self.timestamp}"
