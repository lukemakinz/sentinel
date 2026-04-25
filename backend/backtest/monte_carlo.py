"""Monte Carlo permutation test for backtest results."""
import random
import math
from dataclasses import dataclass

from .metrics import compute_sharpe, compute_max_drawdown

RUIN_THRESHOLD = 0.50  # Portfolio is "ruined" if it drops below 50% of initial capital


@dataclass
class MonteCarloResult:
    total_simulations:     int
    ruin_probability:      float
    median_final_capital:  float
    worst_5pct_drawdown:   float
    median_sharpe:         float


def run_monte_carlo(pnls: list[float], n_simulations: int = 10_000,
                    initial_capital: float = 10_000.0) -> MonteCarloResult:
    if not pnls:
        return MonteCarloResult(0, 0.0, initial_capital, 0.0, 0.0)

    ruin_count    = 0
    final_caps    = []
    drawdowns     = []
    sharpes       = []

    for _ in range(n_simulations):
        sim_pnls = random.sample(pnls, len(pnls))  # shuffle order
        equity   = initial_capital
        curve    = [equity]
        returns  = []

        for pnl in sim_pnls:
            equity += pnl
            curve.append(equity)
            returns.append(pnl / initial_capital * 100)
            if equity <= 0:
                break

        if equity < initial_capital * (1 - RUIN_THRESHOLD):
            ruin_count += 1

        final_caps.append(equity)
        drawdowns.append(compute_max_drawdown(curve))
        sharpes.append(compute_sharpe(returns))

    final_caps.sort()
    drawdowns.sort()
    sharpes.sort()

    n = len(final_caps)
    worst_5pct_idx = max(0, int(n * 0.05) - 1)

    return MonteCarloResult(
        total_simulations=n_simulations,
        ruin_probability=round(ruin_count / n_simulations, 4),
        median_final_capital=round(final_caps[n // 2], 2),
        worst_5pct_drawdown=round(drawdowns[worst_5pct_idx], 2),
        median_sharpe=round(sharpes[n // 2], 3),
    )
