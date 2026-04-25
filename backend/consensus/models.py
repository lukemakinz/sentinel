from django.db import models


class ConsensusSignal(models.Model):
    """Aggregated consensus signal from all analysts."""
    TIER_CHOICES = [
        ('NONE', 'No Signal'),
        ('WATCH', 'Watch'),
        ('SIGNAL', 'Signal'),
        ('HIGH_CONVICTION', 'High Conviction'),
    ]

    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    conviction_score = models.FloatField()  # -100 to +100
    bias = models.CharField(max_length=10)
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, default='NONE')
    agreeing_analysts = models.IntegerField(default=0)
    total_analysts = models.IntegerField(default=6)

    # Individual scores snapshot
    momentum_score = models.FloatField(default=0)
    volume_flow_score = models.FloatField(default=0)
    structure_score = models.FloatField(default=0)
    sentiment_score = models.FloatField(default=0)
    llm_narrative_score = models.FloatField(default=0)
    cross_asset_score = models.FloatField(default=0)

    analyst_details = models.JSONField(default=dict, blank=True)
    action_taken = models.BooleanField(default=False)

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['symbol', '-timestamp'])]

    def __str__(self):
        return f"{self.symbol} {self.conviction_score:+.0f} [{self.tier}] @ {self.timestamp}"
