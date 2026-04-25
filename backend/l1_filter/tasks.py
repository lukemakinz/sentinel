"""Celery tasks for L1 Pre-Filter scanning."""
import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(name='l1_filter.scan_all_symbols')
def scan_all_symbols():
    """
    Run L1Scanner for every watched pair.
    Checks all 3 strategies simultaneously.
    On pass → triggers L2 agents for each passing strategy.
    """
    from .scanner import L1Scanner
    from .strategies import evaluate_strategies, STRATEGIES
    from ingester.models import WatchedPair, WhaleCVD
    from l2_agents.tasks import run_l2_analysis
    from django.utils import timezone
    from datetime import timedelta

    scanner = L1Scanner()
    results = {}

    for symbol in WatchedPair.get_active_symbols():
        try:
            # Run full gate scan (all 15 gates)
            ctx = scanner.scan(symbol)

            # Check if WhaleCVD data exists (required for S2)
            cutoff = timezone.now() - timedelta(hours=4)
            has_cvd = WhaleCVD.objects.filter(symbol=symbol, timestamp__gte=cutoff).exists()

            if ctx:
                gates_a = ctx.get('gates_a', {})
                gates_b = ctx.get('gates_b', {})
                gates_c = ctx.get('gates_c', {})

                passing = evaluate_strategies(gates_a, gates_b, gates_c, has_whale_cvd=has_cvd)
                results[symbol] = passing or 'FAIL'

                for strategy_id in passing:
                    ctx_with_strategy = {**ctx, 'strategy': strategy_id}
                    logger.info(
                        f"L1 PASS [{strategy_id} — {STRATEGIES[strategy_id]['name']}]: "
                        f"{symbol} {ctx['direction']} → L2"
                    )
                    run_l2_analysis.delay(ctx_with_strategy)

                if not passing:
                    logger.debug(f"L1 gates passed but no strategy met criteria: {symbol}")
            else:
                results[symbol] = 'FAIL'

        except Exception as e:
            logger.error(f"L1 scan error {symbol}: {e}", exc_info=True)
            results[symbol] = 'ERROR'

    return results
