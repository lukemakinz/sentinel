from django.db import models


class L2Decision(models.Model):
    ACTION_CHOICES = [('APPROVE', 'Approve'), ('REJECT', 'Reject')]

    symbol          = models.CharField(max_length=20, db_index=True)
    timestamp       = models.DateTimeField(auto_now_add=True, db_index=True)
    direction       = models.CharField(max_length=5, default='')
    action          = models.CharField(max_length=10, choices=ACTION_CHOICES)
    size_multiplier = models.FloatField(default=0.0)
    veto_reason     = models.CharField(max_length=50, blank=True)
    agents_summary  = models.JSONField(default=dict)
    trade_context   = models.JSONField(null=True, blank=True)
    trade_params    = models.JSONField(null=True, blank=True)  # L3 entry/SL/TP params
    dismissed       = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes  = [models.Index(fields=['symbol', '-timestamp'])]

    def __str__(self):
        return f"{self.symbol} {self.direction} [{self.action}] ×{self.size_multiplier} @ {self.timestamp}"
