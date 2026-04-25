"""Celery tasks for trade execution and position monitoring."""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='executor.process_signal')
def process_signal(consensus_signal_id):
    """Process a consensus signal through risk manager and potentially execute."""
    from consensus.models import ConsensusSignal
    from risk.manager import RiskManager
    from .paper_engine import PaperTradingEngine
    from ingester.models import Candle
    from django.conf import settings

    try:
        signal = ConsensusSignal.objects.get(id=consensus_signal_id)
    except ConsensusSignal.DoesNotExist:
        return

    if signal.action_taken:
        return

    # Get current price
    latest = Candle.objects.filter(
        symbol=signal.symbol, interval='1m',
    ).order_by('-timestamp').values_list('close', flat=True).first()

    if not latest:
        logger.warning(f"No price data for {signal.symbol}")
        return

    current_price = float(latest)
    side = 'LONG' if signal.bias == 'LONG' else 'SHORT'

    # Risk evaluation
    rm = RiskManager()
    approved, result = rm.evaluate_trade(signal.symbol, side, signal.tier, current_price)

    if not approved:
        logger.info(f"Trade rejected: {signal.symbol} — {result.get('reason', 'unknown')}")
        signal.action_taken = True
        signal.save()
        return

    # Execute based on mode
    mode = settings.TRADING_MODE

    if mode == 'paper':
        engine = PaperTradingEngine()
        engine.open_position(result, signal)
    elif mode == 'signal_only':
        logger.info(f"🔔 SIGNAL: {signal.symbol} {side} (signal_only mode)")
    else:
        logger.info(f"Mode '{mode}' — no auto execution")

    signal.action_taken = True
    signal.save()


@shared_task(name='executor.monitor_positions')
def monitor_positions():
    """Check open positions for SL/TP hits — runs every 30 seconds."""
    from .paper_engine import PaperTradingEngine
    engine = PaperTradingEngine()
    engine.check_positions()


@shared_task(name='executor.daily_reset')
def daily_reset():
    """Reset daily risk counters — runs at midnight UTC."""
    from risk.kill_switches import reset_daily
    reset_daily()
    logger.info("Daily risk counters reset")


@shared_task(name='executor.weekly_reset')
def weekly_reset():
    """Reset weekly risk counters — runs Monday midnight UTC."""
    from risk.kill_switches import reset_weekly
    reset_weekly()
    logger.info("Weekly risk counters reset")
