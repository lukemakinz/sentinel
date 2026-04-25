from django.db import models


class Position(models.Model):
    """Active trading position."""
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('CLOSED', 'Closed'),
        ('CANCELLED', 'Cancelled'),
    ]
    SIDE_CHOICES = [('LONG', 'Long'), ('SHORT', 'Short')]

    symbol = models.CharField(max_length=20, db_index=True)
    side = models.CharField(max_length=5, choices=SIDE_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN')

    entry_price = models.FloatField()
    current_price = models.FloatField(default=0)
    quantity = models.FloatField()
    position_size_usd = models.FloatField()
    leverage = models.IntegerField(default=1)

    stop_loss = models.FloatField()
    take_profit_1 = models.FloatField(null=True)
    take_profit_2 = models.FloatField(null=True)
    take_profit_3 = models.FloatField(null=True)
    tp1_hit = models.BooleanField(default=False)
    tp2_hit = models.BooleanField(default=False)
    tp3_hit = models.BooleanField(default=False)
    sl_moved_to_be   = models.BooleanField(default=False)
    chandelier_stop  = models.FloatField(null=True, blank=True)
    strategy         = models.CharField(max_length=5, default='S1')
    source           = models.CharField(max_length=10, default='auto')   # 'auto' | 'manual'
    margin_usd       = models.FloatField(default=0)                      # Collateral for leveraged trades
    liquidation_price = models.FloatField(null=True, blank=True)        # Pre-computed liq price

    remaining_quantity = models.FloatField(default=0)
    realized_pnl = models.FloatField(default=0)
    unrealized_pnl = models.FloatField(default=0)

    consensus_signal_id = models.IntegerField(null=True)
    tier = models.CharField(max_length=20, blank=True)
    analyst_snapshot = models.JSONField(default=dict, blank=True)

    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['-opened_at']
        indexes = [models.Index(fields=['status', 'symbol'])]

    def __str__(self):
        return f"{self.symbol} {self.side} {self.status} | PnL: {self.unrealized_pnl:+.2f}"

    @property
    def pnl_percent(self):
        if self.entry_price == 0:
            return 0
        if self.side == 'LONG':
            return (self.current_price - self.entry_price) / self.entry_price * 100
        else:
            return (self.entry_price - self.current_price) / self.entry_price * 100


class Trade(models.Model):
    """Completed trade record for journal."""
    symbol = models.CharField(max_length=20, db_index=True)
    side = models.CharField(max_length=5)
    entry_price = models.FloatField()
    exit_price = models.FloatField()
    quantity = models.FloatField()
    position_size_usd = models.FloatField()
    pnl = models.FloatField()
    pnl_percent = models.FloatField()
    risk_reward = models.FloatField(default=0)

    entry_time = models.DateTimeField()
    exit_time = models.DateTimeField()
    duration_minutes = models.IntegerField(default=0)

    tier = models.CharField(max_length=20, blank=True)
    close_reason = models.CharField(max_length=50, blank=True)
    analyst_snapshot = models.JSONField(default=dict, blank=True)
    conviction_score = models.FloatField(default=0)

    class Meta:
        ordering = ['-exit_time']

    def __str__(self):
        return f"{self.symbol} {self.side} PnL:{self.pnl:+.2f} RR:{self.risk_reward:.1f}"


class TaxEvent(models.Model):
    """PIT-38 tax record — created automatically on every closed trade."""
    trade      = models.OneToOneField('Trade', on_delete=models.CASCADE, related_name='tax_event')
    symbol     = models.CharField(max_length=20, db_index=True)
    side       = models.CharField(max_length=5)
    entry_price = models.FloatField()
    exit_price  = models.FloatField()
    quantity    = models.FloatField()
    pnl_usd    = models.FloatField()
    close_date = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-close_date']

    def __str__(self):
        sign = '+' if self.pnl_usd >= 0 else ''
        return f"{self.symbol} {self.side} {sign}${self.pnl_usd:.2f} @ {self.close_date}"


class AccountState(models.Model):
    """Account balance and equity tracking."""
    updated_at = models.DateTimeField(auto_now=True)
    balance = models.FloatField()
    equity = models.FloatField()
    unrealized_pnl = models.FloatField(default=0)
    total_trades = models.IntegerField(default=0)
    winning_trades = models.IntegerField(default=0)
    losing_trades = models.IntegerField(default=0)
    total_pnl = models.FloatField(default=0)
    max_drawdown = models.FloatField(default=0)
    peak_equity = models.FloatField(default=0)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        wr = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        return f"Balance: ${self.balance:,.2f} | WR: {wr:.0f}%"
