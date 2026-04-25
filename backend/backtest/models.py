from django.db import models


class BacktestRun(models.Model):
    STATUS = [('pending', 'Pending'), ('running', 'Running'),
              ('done', 'Done'), ('error', 'Error')]

    symbol          = models.CharField(max_length=20, db_index=True)
    strategy        = models.CharField(max_length=5)
    start_date      = models.DateField()
    end_date        = models.DateField()
    initial_capital = models.FloatField(default=10000.0)
    risk_per_trade  = models.FloatField(default=0.005)
    status          = models.CharField(max_length=10, choices=STATUS, default='pending')
    created_at      = models.DateTimeField(auto_now_add=True)
    completed_at    = models.DateTimeField(null=True, blank=True)
    error_message   = models.TextField(blank=True)

    # Results
    total_trades    = models.IntegerField(default=0)
    winning_trades  = models.IntegerField(default=0)
    win_rate        = models.FloatField(default=0)
    sharpe_ratio    = models.FloatField(default=0)
    calmar_ratio    = models.FloatField(default=0)
    max_drawdown    = models.FloatField(default=0)
    total_pnl       = models.FloatField(default=0)
    total_pnl_pct   = models.FloatField(default=0)
    final_capital   = models.FloatField(default=0)

    # Monte Carlo
    mc_ruin_probability   = models.FloatField(null=True)
    mc_worst_5pct_dd      = models.FloatField(null=True)
    mc_median_sharpe      = models.FloatField(null=True)

    # JSON
    equity_curve    = models.JSONField(default=list, blank=True)
    trades_detail   = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.symbol}/{self.strategy} [{self.status}] Sharpe={self.sharpe_ratio:.2f}"

    def passes_live_threshold(self) -> bool:
        return (self.sharpe_ratio > 1.5 and self.max_drawdown < 20.0
                and self.total_trades >= 300 and self.calmar_ratio > 0.5)
