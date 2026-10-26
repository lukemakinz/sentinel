from django.db import models


class CarryEpisode(models.Model):
    """One paper-only funding-carry holding period (long spot / short USD-M
    perpetual, equal quantity), tracked with real market prices fetched live.

    Paper only — no orders are ever placed. This exists purely to collect
    honest forward-test data. No model in this app can place an order.
    """
    STATUS_CHOICES = [('OPEN', 'Open'), ('CLOSED', 'Closed')]

    symbol = models.CharField(max_length=20, db_index=True)
    strategy = models.CharField(max_length=30, default='S11_LEGACY', db_index=True)
    protocol_sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN', db_index=True)

    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    spot_entry_price = models.FloatField()
    perp_entry_price = models.FloatField()
    spot_exit_price = models.FloatField(null=True, blank=True)
    perp_exit_price = models.FloatField(null=True, blank=True)

    notional_usd = models.FloatField()
    quantity = models.FloatField()
    futures_margin_usd = models.FloatField(default=0.0)
    reserve_usd = models.FloatField(default=0.0)

    qualifying_funding_bps = models.FloatField()
    entry_reason = models.CharField(max_length=30)
    exit_reason = models.CharField(max_length=30, blank=True)

    funding_accrued_usd = models.FloatField(default=0.0)
    adverse_funding_usd = models.FloatField(default=0.0)
    last_funding_accrued_at = models.DateTimeField(null=True, blank=True)
    estimated_costs_usd = models.FloatField(default=0.0)
    realized_pnl_usd = models.FloatField(null=True, blank=True)
    stress_costs_usd = models.FloatField(default=0.0)
    stress_pnl_usd = models.FloatField(null=True, blank=True)
    severe_costs_usd = models.FloatField(default=0.0)
    severe_pnl_usd = models.FloatField(null=True, blank=True)
    min_futures_equity_usd = models.FloatField(null=True, blank=True)
    max_mark_leverage = models.FloatField(null=True, blank=True)
    last_safety_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-opened_at']
        indexes = [models.Index(fields=['status', 'symbol'])]
        constraints = [
            models.UniqueConstraint(
                fields=['strategy'],
                condition=models.Q(status='OPEN'),
                name='one_open_carry_episode_per_strategy',
            ),
        ]

    def __str__(self):
        return f"{self.symbol} {self.status} opened {self.opened_at:%Y-%m-%d}"


class CarryDecisionLog(models.Model):
    """Append-only audit trail of every monthly decision evaluation, even
    when the decision is to hold cash or hold the existing position — proves
    the frozen rule ran on schedule even when nothing changed."""
    decision_time = models.DateTimeField(db_index=True)
    strategy = models.CharField(max_length=30, default='S11_LEGACY', db_index=True)
    protocol_sha256 = models.CharField(max_length=64, blank=True)
    previous_symbol = models.CharField(max_length=20, blank=True)
    target_symbol = models.CharField(max_length=20, blank=True)
    reason = models.CharField(max_length=30)
    scores_bps = models.JSONField(default=dict)
    features = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-decision_time']
        constraints = [
            models.UniqueConstraint(
                fields=['strategy', 'decision_time'],
                name='unique_carry_decision_per_strategy_month',
            ),
        ]

    def __str__(self):
        return f"{self.decision_time:%Y-%m-01} {self.previous_symbol}->{self.target_symbol} ({self.reason})"
