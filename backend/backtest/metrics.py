"""Backtest performance metrics."""
import math
from dataclasses import dataclass, field


def compute_sharpe(returns: list[float], risk_free: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    adj_returns = [r - risk_free for r in returns]
    adj_mean = sum(adj_returns) / len(adj_returns)
    variance = sum((r - adj_mean) ** 2 for r in adj_returns) / (len(adj_returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 1.0 if adj_mean > 0 else (-1.0 if adj_mean < 0 else 0.0)
    return adj_mean / std


def compute_max_drawdown(equity_curve: list[float]) -> float:
    """Returns max drawdown as positive percentage (e.g. 15.0 = 15%)."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def compute_calmar(returns: list[float], equity_curve: list[float]) -> float:
    if not returns:
        return 0.0
    annual_return = sum(returns)
    max_dd = compute_max_drawdown(equity_curve)
    if max_dd == 0:
        return float('inf') if annual_return > 0 else 0.0
    return annual_return / max_dd


def compute_win_rate(pnls: list[float]) -> float:
    if not pnls:
        return 0.0
    return sum(1 for p in pnls if p > 0) / len(pnls)


def compute_expected_value(pnls: list[float]) -> float:
    if not pnls:
        return 0.0
    return sum(pnls) / len(pnls)


@dataclass
class BacktestMetrics:
    total_trades:   int   = 0
    winning_trades: int   = 0
    losing_trades:  int   = 0
    win_rate:       float = 0.0
    sharpe_ratio:   float = 0.0
    calmar_ratio:   float = 0.0
    max_drawdown:   float = 0.0
    total_pnl:      float = 0.0
    total_pnl_pct:  float = 0.0
    expected_value: float = 0.0
    initial_capital: float = 10000.0
    final_capital:  float = 10000.0
    equity_curve:   list  = field(default_factory=list)
    trades:         list  = field(default_factory=list)

    @classmethod
    def from_trades(cls, trades: list[dict], equity_curve: list[float],
                    initial_capital: float = 10000.0) -> 'BacktestMetrics':
        if not trades:
            return cls(initial_capital=initial_capital, final_capital=initial_capital,
                       equity_curve=equity_curve or [initial_capital])

        pnls     = [t['pnl'] for t in trades]
        pnl_pcts = [t.get('pnl_pct', t['pnl'] / initial_capital * 100) for t in trades]
        wins     = sum(1 for p in pnls if p > 0)

        return cls(
            total_trades=len(trades),
            winning_trades=wins,
            losing_trades=len(trades) - wins,
            win_rate=compute_win_rate(pnls),
            sharpe_ratio=round(compute_sharpe(pnl_pcts), 3),
            calmar_ratio=round(compute_calmar(pnl_pcts, equity_curve), 3),
            max_drawdown=round(compute_max_drawdown(equity_curve), 2),
            total_pnl=round(sum(pnls), 2),
            total_pnl_pct=round(sum(pnl_pcts), 2),
            expected_value=round(compute_expected_value(pnls), 2),
            initial_capital=initial_capital,
            final_capital=equity_curve[-1] if equity_curve else initial_capital,
            equity_curve=equity_curve,
            trades=trades,
        )

    def passes_live_threshold(self) -> bool:
        return (
            self.sharpe_ratio > 1.5 and
            self.max_drawdown < 20.0 and
            self.total_trades >= 300 and
            self.calmar_ratio > 0.5
        )
