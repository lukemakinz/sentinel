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


class AuctionAnalysis(models.Model):
    """Immutable audit record for the shadow market-state adjudicator."""
    ACTION_CHOICES = [('PASS', 'Pass'), ('WAIT', 'Wait'), ('ARM', 'Arm')]

    symbol = models.CharField(max_length=20, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    snapshot_hash = models.CharField(max_length=64, db_index=True)
    snapshot_version = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=64, blank=True)
    provider = models.CharField(max_length=30, blank=True)
    model = models.CharField(max_length=80, blank=True)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    direction = models.CharField(max_length=5, default='NONE')
    strategy_id = models.CharField(max_length=64, default='NONE')
    snapshot = models.JSONField(default=dict)
    decision = models.JSONField(default=dict)
    runtime = models.JSONField(default=dict)
    shadow_only = models.BooleanField(default=True)
    cycle_key = models.CharField(
        max_length=64, null=True, blank=True, unique=True,
        help_text='Idempotency key for scheduled per-bar analysis cycles.',
    )

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['symbol', '-timestamp'])]

    def __str__(self):
        return f"{self.symbol} {self.action} {self.direction} [{self.strategy_id}]"


class AuctionShadowPlan(models.Model):
    """Replayable, non-executable geometry created from an AI ``ARM`` decision."""

    STATE_CHOICES = [
        ('ARMED', 'Armed'),
        ('TRIGGERED', 'Triggered'),
        ('CLOSED', 'Closed'),
        ('EXPIRED', 'Expired'),
        ('INVALID', 'Invalid before entry'),
    ]
    EXIT_CHOICES = [
        ('', 'Open'),
        ('TARGET', 'Target'),
        ('STOP', 'Stop'),
        ('TIME', 'Time expiry'),
        ('NO_TRIGGER', 'No trigger'),
        ('PRE_INVALIDATION', 'Invalidated before trigger'),
    ]

    analysis = models.OneToOneField(
        AuctionAnalysis, on_delete=models.CASCADE, related_name='shadow_plan',
    )
    symbol = models.CharField(max_length=20, db_index=True)
    strategy_id = models.CharField(max_length=64, db_index=True)
    direction = models.CharField(max_length=5)
    zone_kind = models.CharField(max_length=40)
    zone_low = models.FloatField()
    zone_high = models.FloatField()
    structural_stop = models.FloatField()
    target_r = models.FloatField(default=1.5)
    management_policy = models.CharField(max_length=32)
    armed_at = models.DateTimeField(db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    state = models.CharField(
        max_length=12, choices=STATE_CHOICES, default='ARMED', db_index=True,
    )
    triggered_at = models.DateTimeField(null=True, blank=True)
    entry_price = models.FloatField(null=True, blank=True)
    target_price = models.FloatField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    exit_price = models.FloatField(null=True, blank=True)
    exit_reason = models.CharField(max_length=20, choices=EXIT_CHOICES, blank=True)
    gross_r = models.FloatField(null=True, blank=True)
    net_r = models.FloatField(null=True, blank=True)
    mfe_r = models.FloatField(null=True, blank=True)
    mae_r = models.FloatField(null=True, blank=True)
    cost_assumptions = models.JSONField(default=dict)
    trigger_evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-armed_at']
        indexes = [
            models.Index(fields=['state', 'expires_at']),
            models.Index(fields=['symbol', '-armed_at']),
        ]

    def __str__(self):
        return f"{self.symbol} {self.direction} {self.strategy_id} [{self.state}]"
