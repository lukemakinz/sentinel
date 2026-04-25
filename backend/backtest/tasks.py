"""Celery task: async backtest execution."""
import logging
from datetime import date

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name='backtest.run_backtest', bind=True)
def run_backtest(self, backtest_run_id: int):
    """Execute backtest asynchronously. Updates BacktestRun status."""
    from .models import BacktestRun
    from .simulator import BacktestSimulator, BacktestConfig
    from .monte_carlo import run_monte_carlo
    from datetime import datetime, timezone as dt_tz

    run = BacktestRun.objects.get(pk=backtest_run_id)
    run.status = 'running'
    run.save()

    try:
        config = BacktestConfig(
            symbol=run.symbol,
            strategy=run.strategy,
            start_date=datetime.combine(run.start_date, datetime.min.time()).replace(tzinfo=dt_tz.utc),
            end_date=datetime.combine(run.end_date, datetime.min.time()).replace(tzinfo=dt_tz.utc),
            initial_capital=run.initial_capital,
            risk_per_trade=run.risk_per_trade,
        )

        metrics = BacktestSimulator(config).run()

        # Monte Carlo on closed trade PnLs
        pnls = [t['pnl'] for t in metrics.trades]
        mc   = run_monte_carlo(pnls, n_simulations=5000, initial_capital=run.initial_capital)

        run.total_trades   = metrics.total_trades
        run.winning_trades = metrics.winning_trades
        run.win_rate       = metrics.win_rate
        run.sharpe_ratio   = metrics.sharpe_ratio
        run.calmar_ratio   = metrics.calmar_ratio
        run.max_drawdown   = metrics.max_drawdown
        run.total_pnl      = metrics.total_pnl
        run.total_pnl_pct  = metrics.total_pnl_pct
        run.final_capital  = metrics.final_capital
        run.equity_curve   = metrics.equity_curve[::60]  # sample every 60 points
        run.trades_detail  = metrics.trades[:500]         # cap to 500 for storage

        run.mc_ruin_probability = mc.ruin_probability
        run.mc_worst_5pct_dd   = mc.worst_5pct_drawdown
        run.mc_median_sharpe   = mc.median_sharpe

        run.status       = 'done'
        run.completed_at = timezone.now()
        run.save()

        logger.info(f"Backtest {backtest_run_id} done: "
                    f"{metrics.total_trades} trades, Sharpe={metrics.sharpe_ratio:.2f}")
        return {'status': 'done', 'sharpe': metrics.sharpe_ratio}

    except Exception as e:
        run.status        = 'error'
        run.error_message = str(e)
        run.completed_at  = timezone.now()
        run.save()
        logger.error(f"Backtest {backtest_run_id} error: {e}", exc_info=True)
        raise
