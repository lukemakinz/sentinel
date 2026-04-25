from django.db import models


class L1Result(models.Model):
    DIRECTION_CHOICES = [('LONG', 'Long'), ('SHORT', 'Short'), ('', 'Unknown')]

    symbol    = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    direction = models.CharField(max_length=5, choices=DIRECTION_CHOICES, default='')
    passed    = models.BooleanField(db_index=True)

    gates_a       = models.JSONField(default=dict)
    gates_b       = models.JSONField(default=dict)
    gates_c       = models.JSONField(default=dict)
    gates_b_count = models.IntegerField(default=0)
    gates_c_count = models.IntegerField(default=0)
    trade_context = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['symbol', '-timestamp'])]

    def __str__(self):
        status = 'PASS' if self.passed else 'FAIL'
        return f"{self.symbol} {self.direction} [{status}] @ {self.timestamp}"
