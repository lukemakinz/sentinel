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


class SetupObservation(models.Model):
    """Prospective journal of setup-search findings and their outcomes.

    ``SETUP`` rows are MSS-confirmed setups keyed by their MSS bar and resolved
    on closed 15m bars against TP1 (nearest BSL) with stress costs. ``EPISODE``
    rows are live sweeps waiting for MSS; they record whether an MSS followed.
    """
    KIND_CHOICES = [('SETUP', 'MSS-confirmed setup'), ('EPISODE', 'Sweep awaiting MSS')]
    OUTCOME_CHOICES = [
        ('OPEN', 'Open'), ('FILLED', 'Filled, in position'), ('TP1_HIT', 'TP1 hit'),
        ('STOPPED', 'Stopped'), ('TIME', 'Time exit'), ('EXPIRED', 'Limit expired'),
        ('MSS', 'Episode reached MSS'), ('NO_MSS', 'Episode ended without MSS'),
    ]

    key = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, db_index=True)
    symbol = models.CharField(max_length=30, db_index=True)
    side = models.CharField(max_length=5)
    first_seen = models.DateTimeField(auto_now_add=True, db_index=True)
    last_seen = models.DateTimeField(auto_now=True)
    event_time = models.DateTimeField(db_index=True)  # MSS close or sweep close
    first_status = models.CharField(max_length=20)
    last_status = models.CharField(max_length=20)
    score = models.IntegerField(default=0)
    entry_limit = models.FloatField(null=True)
    stop_loss = models.FloatField(null=True)
    tp1 = models.FloatField(null=True)
    rr_tp1 = models.FloatField(null=True)
    strict_rr_ok = models.BooleanField(default=False)
    absorption = models.CharField(max_length=20, blank=True, default='')
    payload = models.JSONField(default=dict)
    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES, default='OPEN', db_index=True)
    filled_at = models.DateTimeField(null=True)
    resolved_at = models.DateTimeField(null=True)
    net_r = models.FloatField(null=True)
    alerted = models.BooleanField(default=False)

    class Meta:
        ordering = ['-event_time']

    def __str__(self):
        return f"{self.symbol} {self.side} {self.kind} {self.outcome}"
