"""Strategy Monitor — rolling 30-trade health check."""
import logging
import math

logger = logging.getLogger(__name__)

_MIN_TRADES       = 10   # Minimum trades before evaluating
_ROLLING_WINDOW   = 30   # Trade count for rolling metrics
_HALT_WINDOW      = 20   # Consecutive trades for Sharpe check
_HALT_SHARPE      = 0.0  # Auto-halt threshold


def compute_rolling_sharpe(returns: list[float]) -> float:
    """Annualised-ish Sharpe: mean/std of returns. Returns 0 if std=0 or empty."""
    if not returns:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n
    if n < 2:
        return 0.0
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        # All identical returns: sign of mean determines direction
        return 1.0 if mean > 0 else (-1.0 if mean < 0 else 0.0)
    return mean / std


def check_strategy_health() -> tuple[bool, str]:
    """
    Returns (ok, reason).
    Auto-halts if last 20-trade rolling Sharpe < 0.
    """
    from executor.models import Trade

    last_trades = list(
        Trade.objects.order_by('-exit_time')
        .values_list('pnl_percent', flat=True)[:_ROLLING_WINDOW]
    )

    if len(last_trades) < _MIN_TRADES:
        return True, f"Insufficient trade history ({len(last_trades)}/{_MIN_TRADES})"

    returns = list(reversed(last_trades))  # oldest first

    # Rolling window for halt check
    halt_window = returns[-_HALT_WINDOW:] if len(returns) >= _HALT_WINDOW else returns
    rolling_sharpe = compute_rolling_sharpe(halt_window)

    if len(halt_window) >= _HALT_WINDOW and rolling_sharpe < _HALT_SHARPE:
        msg = f"Strategy degraded: {_HALT_WINDOW}-trade Sharpe={rolling_sharpe:.2f}"
        logger.warning(f"🛑 STRATEGY HALT: {msg}")
        return False, msg

    overall_sharpe = compute_rolling_sharpe(returns)
    wins = sum(1 for r in returns if r > 0)
    win_rate = wins / len(returns)
    return True, f"Healthy: WR={win_rate:.0%} Sharpe={overall_sharpe:.2f}"
