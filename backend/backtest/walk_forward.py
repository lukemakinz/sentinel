"""Walk-forward analysis — rolling window out-of-sample validation."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .metrics import BacktestMetrics


@dataclass
class WalkForwardWindow:
    train_start: datetime
    train_end:   datetime
    test_start:  datetime
    test_end:    datetime
    train_metrics: Optional[BacktestMetrics] = None
    test_metrics:  Optional[BacktestMetrics] = None

    @property
    def degradation_ratio(self) -> float:
        """Test Sharpe / Train Sharpe. > 0.5 = acceptable."""
        if not self.train_metrics or not self.test_metrics:
            return 0.0
        if self.train_metrics.sharpe_ratio == 0:
            return 0.0
        return self.test_metrics.sharpe_ratio / self.train_metrics.sharpe_ratio


@dataclass
class WalkForwardResult:
    windows:            list[WalkForwardWindow] = field(default_factory=list)
    avg_degradation:    float = 0.0
    stable:             bool  = False   # True if avg degradation > 0.5
    avg_test_sharpe:    float = 0.0
    avg_test_drawdown:  float = 0.0

    def summary(self) -> str:
        status = "STABLE ✅" if self.stable else "UNSTABLE ⚠️"
        return (f"Walk-Forward [{status}] "
                f"Avg Degradation: {self.avg_degradation:.2f} "
                f"Avg Test Sharpe: {self.avg_test_sharpe:.2f} "
                f"Avg Test MaxDD: {self.avg_test_drawdown:.1f}%")


def run_walk_forward(symbol: str, strategy: str,
                     start: datetime, end: datetime,
                     train_months: int = 12,
                     test_months:  int = 3,
                     initial_capital: float = 10_000.0,
                     risk_per_trade:  float = 0.005) -> WalkForwardResult:
    """
    Rolling walk-forward: train on N months, test on M months, slide forward.
    Returns WalkForwardResult with per-window metrics.
    """
    from .simulator import BacktestSimulator, BacktestConfig

    windows: list[WalkForwardWindow] = []
    cursor = start

    while cursor + timedelta(days=30 * (train_months + test_months)) <= end:
        train_start = cursor
        train_end   = cursor + timedelta(days=30 * train_months)
        test_start  = train_end
        test_end    = train_end + timedelta(days=30 * test_months)

        window = WalkForwardWindow(train_start=train_start, train_end=train_end,
                                   test_start=test_start,  test_end=test_end)

        for phase, (s, e) in [('train', (train_start, train_end)),
                               ('test',  (test_start,  test_end))]:
            cfg = BacktestConfig(symbol=symbol, strategy=strategy,
                                 start_date=s, end_date=e,
                                 initial_capital=initial_capital,
                                 risk_per_trade=risk_per_trade)
            metrics = BacktestSimulator(cfg).run()
            if phase == 'train':
                window.train_metrics = metrics
            else:
                window.test_metrics = metrics

        windows.append(window)
        cursor += timedelta(days=30 * test_months)  # slide by test period

    if not windows:
        return WalkForwardResult()

    degradations    = [w.degradation_ratio for w in windows if w.train_metrics and w.test_metrics]
    test_sharpes    = [w.test_metrics.sharpe_ratio for w in windows if w.test_metrics]
    test_drawdowns  = [w.test_metrics.max_drawdown for w in windows if w.test_metrics]

    avg_deg = sum(degradations) / len(degradations) if degradations else 0
    avg_sh  = sum(test_sharpes)  / len(test_sharpes)  if test_sharpes  else 0
    avg_dd  = sum(test_drawdowns) / len(test_drawdowns) if test_drawdowns else 0

    return WalkForwardResult(
        windows=windows,
        avg_degradation=round(avg_deg, 3),
        stable=avg_deg >= 0.5,
        avg_test_sharpe=round(avg_sh, 3),
        avg_test_drawdown=round(avg_dd, 2),
    )
