from django.db import models


class AnalystSignalRecord(models.Model):
    """Persisted analyst signals for history and dashboard."""
    analyst_name = models.CharField(max_length=30, db_index=True)
    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    score = models.FloatField()
    bias = models.CharField(max_length=10)
    confidence = models.FloatField()
    reasoning = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['analyst_name', 'symbol', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.analyst_name} | {self.symbol} | {self.score:+.0f} ({self.bias})"
