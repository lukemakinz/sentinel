"""Signal Evaluator — tracks full lifecycle of every signal for learning."""
from django.db import models


class Signal(models.Model):
    """Full lifecycle of a trading signal — from generation to outcome."""

    # ── Strategy & identity ───────────────────────────────────────────────────
    symbol    = models.CharField(max_length=20, db_index=True)
    direction = models.CharField(max_length=5)   # LONG / SHORT
    strategy  = models.CharField(max_length=5)   # S1 / S2 / S3
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at  = models.DateTimeField(null=True)   # created_at + 24h

    # ── Setup parameters (from L3) ────────────────────────────────────────────
    entry_price   = models.FloatField(null=True)
    stop_loss     = models.FloatField(null=True)
    take_profit_1 = models.FloatField(null=True)
    take_profit_2 = models.FloatField(null=True)
    r_value       = models.FloatField(null=True)    # SL distance in price
    rr_planned    = models.FloatField(null=True)    # (TP1-entry) / (entry-SL)

    # ── L1 attribution ────────────────────────────────────────────────────────
    gates_a_passed = models.JSONField(default=dict)
    gates_b_passed = models.JSONField(default=dict)
    gates_c_passed = models.JSONField(default=dict)
    regime         = models.CharField(max_length=20, blank=True)   # trending/choppy
    session        = models.CharField(max_length=10, blank=True)   # london/ny/off
    htf_bias       = models.CharField(max_length=10, blank=True)   # bullish/bearish
    choppiness_index = models.FloatField(null=True)

    # ── L2 attribution ────────────────────────────────────────────────────────
    l2_action          = models.CharField(max_length=10, blank=True)   # APPROVE/REJECT/NONE
    l2_size_multiplier = models.FloatField(default=1.0)
    agent_verdicts     = models.JSONField(default=dict)    # {agent: {verdict, confidence}}
    veto_reason        = models.CharField(max_length=50, blank=True)

    # ── Execution ─────────────────────────────────────────────────────────────
    executed       = models.BooleanField(default=False)   # user clicked "Wchodzę"
    shadow         = models.BooleanField(default=False)   # tracked but not executed
    position_size_usd = models.FloatField(null=True)
    is_reentry_of  = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reentries")

    # ── Lifecycle state ───────────────────────────────────────────────────────
    STATE_CHOICES = [
        ('GENERATED', 'Generated'),
        ('APPROVED',  'L2 Approved'),
        ('REJECTED',  'L2 Rejected'),
        ('MONITORING', 'Monitoring'),
        ('CLOSED',    'Closed'),
        ('EXPIRED',   'Expired'),
    ]
    state      = models.CharField(max_length=12, choices=STATE_CHOICES, default='GENERATED', db_index=True)
    closed_at  = models.DateTimeField(null=True)
    exit_price = models.FloatField(null=True)
    EXIT_REASONS = [
        ('SL', 'Stop Loss'), ('TP1', 'Take Profit 1'), ('TP2', 'Take Profit 2'),
        ('RUNNER_TRAIL', 'Runner Trailing'), ('TIME_KILL', 'Time Kill'),
        ('EOD', 'End of Day'), ('MANUAL', 'Manual Close'), ('EXPIRED', 'Signal Expired'),
    ]
    exit_reason = models.CharField(max_length=15, choices=EXIT_REASONS, blank=True)

    # ── Outcome ───────────────────────────────────────────────────────────────
    OUTCOME_CHOICES = [
        ('WIN', 'Win'), ('LOSS', 'Loss'), ('BREAKEVEN', 'Breakeven'),
        ('PARTIAL_WIN', 'Partial Win'), ('EXPIRED', 'Expired'),
    ]
    outcome           = models.CharField(max_length=12, choices=OUTCOME_CHOICES, blank=True)
    pnl_r             = models.FloatField(null=True)    # PnL in R multiples
    pnl_usd           = models.FloatField(null=True)
    mfe_r             = models.FloatField(null=True)    # Max Favorable Excursion
    mae_r             = models.FloatField(null=True)    # Max Adverse Excursion
    time_in_trade_min = models.IntegerField(null=True)

    class Meta:
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['symbol', 'strategy', '-created_at']),
            models.Index(fields=['state', 'shadow']),
        ]

    def __str__(self):
        return (f"{self.symbol} {self.direction} [{self.strategy}] "
                f"{self.state} {self.outcome or ''}")

    @property
    def is_win(self):
        return self.outcome in ('WIN', 'PARTIAL_WIN')

    def compute_outcome(self):
        """Derive outcome from exit_reason + pnl_r."""
        if not self.exit_reason or self.pnl_r is None:
            return
        if self.exit_reason == 'SL':
            self.outcome = 'LOSS'
        elif self.exit_reason in ('TP2', 'RUNNER_TRAIL'):
            self.outcome = 'WIN'
        elif self.exit_reason == 'TP1':
            self.outcome = 'PARTIAL_WIN' if self.pnl_r > 0 else 'BREAKEVEN'
        elif self.exit_reason in ('TIME_KILL', 'EOD'):
            self.outcome = 'WIN' if self.pnl_r > 0.1 else 'LOSS' if self.pnl_r < -0.1 else 'BREAKEVEN'
        elif self.exit_reason == 'EXPIRED':
            self.outcome = 'EXPIRED'
