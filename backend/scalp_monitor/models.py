from django.db import models


class ScalpPaperTrade(models.Model):
    """One S20 H1 paper trade (order block + OI confirmation, patient
    breakeven/chandelier exit), tracked with real market prices. Paper
    only — no orders are ever placed. S20 passed development and validation
    under base costs but failed validation stress (PF 0.857 < 1.00), so this
    exists purely to collect honest forward data before any live decision —
    see docs/research/s20_ob_oi_patient_runner/protocol.json.
    """
    STATUS_CHOICES = [('OPEN', 'Open'), ('CLOSED', 'Closed')]
    SIDE_CHOICES = [('LONG', 'Long'), ('SHORT', 'Short')]

    symbol = models.CharField(max_length=20, db_index=True)
    side = models.CharField(max_length=5, choices=SIDE_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN', db_index=True)

    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    entry_price = models.FloatField()
    initial_stop = models.FloatField()
    stop_loss = models.FloatField()
    atr_at_entry = models.FloatField()
    r_value = models.FloatField()  # |entry - initial_stop|, the "1R" unit in price terms
    best_price = models.FloatField()
    breakeven_activated = models.BooleanField(default=False)

    quantity = models.FloatField()
    notional_usd = models.FloatField()

    exit_price = models.FloatField(null=True, blank=True)
    exit_reason = models.CharField(max_length=20, blank=True)
    realized_pnl_usd = models.FloatField(null=True, blank=True)
    r_multiple = models.FloatField(null=True, blank=True)

    setup_id = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-opened_at']
        indexes = [models.Index(fields=['status', 'symbol'])]

    def __str__(self):
        return f"{self.symbol} {self.side} {self.status} opened {self.opened_at:%Y-%m-%d %H:%M}"


class ScalpDecisionLog(models.Model):
    """Append-only audit trail of every evaluation cycle, even when no
    signal fires — proves the frozen S20 H1 rule ran on schedule."""
    checked_at = models.DateTimeField(db_index=True)
    symbol = models.CharField(max_length=20, blank=True)
    action = models.CharField(max_length=30)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-checked_at']

    def __str__(self):
        return f"{self.checked_at:%Y-%m-%d %H:%M} {self.symbol} {self.action}"
