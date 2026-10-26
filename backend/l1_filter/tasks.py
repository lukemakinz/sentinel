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
    from .ai_adjudicator import AI_STRATEGY_ID
    from django.utils import timezone
    from datetime import timedelta

    scanner = L1Scanner()
    results = {}

    for symbol in WatchedPair.get_active_symbols():
        try:
            # Run full gate scan (all 15 gates)
            ctx = scanner.scan(symbol, strategy=None)

            # Check if WhaleCVD data exists (required for S2)
            cutoff = timezone.now() - timedelta(hours=4)
            has_cvd = WhaleCVD.objects.filter(symbol=symbol, timestamp__gte=cutoff).exists()

            if ctx:
                gates_a = ctx.get('gates_a', {})
                gates_b = ctx.get('gates_b', {})
                gates_c = ctx.get('gates_c', {})

                passing = evaluate_strategies(gates_a, gates_b, gates_c, has_whale_cvd=has_cvd, ctx=ctx)
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

            # The X-of-Y/AI path is isolated from conventional strategies and
            # disabled by default.  Approved shadow decisions are never made
            # executable; they are collected for prospective evaluation.
            if getattr(settings, 'AI_ADJUDICATOR_SHADOW_ENABLED', False):
                ai_ctx = scanner.scan(symbol, strategy=AI_STRATEGY_ID)
                if ai_ctx:
                    fingerprint = ai_ctx['ai_candidate']['setup_fingerprint']
                    from l2_agents.models import L2Decision
                    already_reviewed = L2Decision.objects.filter(
                        symbol=symbol,
                        timestamp__gte=timezone.now() - timedelta(hours=24),
                        trade_context__ai_candidate__setup_fingerprint=fingerprint,
                    ).exists()
                    if already_reviewed:
                        logger.debug(f"L2 shadow duplicate suppressed: {symbol} {fingerprint}")
                        continue
                    lock_key = f's12ai:adjudication:{fingerprint}'
                    lock_acquired = True
                    try:
                        from django.core.cache import cache
                        lock_acquired = cache.add(lock_key, 'queued', timeout=24 * 60 * 60)
                    except Exception as exc:
                        # The DB check above still provides a safe fallback when
                        # Redis is temporarily unavailable.
                        logger.warning(f"S12AI dedup cache unavailable: {exc}")
                    if not lock_acquired:
                        logger.debug(f"L2 shadow queue duplicate suppressed: {symbol} {fingerprint}")
                        continue
                    logger.info(
                        f"L1 AI QUORUM {ai_ctx['ai_candidate']['passed_count']}/"
                        f"{ai_ctx['ai_candidate']['total_count']}: {symbol} "
                        f"{ai_ctx['direction']} → L2 shadow"
                    )
                    try:
                        run_l2_analysis.delay(ai_ctx)
                    except Exception:
                        try:
                            cache.delete(lock_key)
                        except Exception:
                            pass
                        raise

        except Exception as e:
            logger.error(f"L1 scan error {symbol}: {e}", exc_info=True)
            results[symbol] = 'ERROR'

    return results
