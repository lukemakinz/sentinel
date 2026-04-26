"""Celery task: run L2 analysis when L1 passes."""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='l2_agents.run_l2_analysis')
def run_l2_analysis(trade_context: dict) -> dict:
    """Run L2 agents → if APPROVE, run L3 Calculator and save trade params."""
    from .orchestrator import L2Orchestrator
    from .models import L2Decision
    symbol = trade_context.get('symbol', '?')
    try:
        decision = L2Orchestrator().run(trade_context)
        logger.info(f"L2 {symbol}: {decision['action']} ×{decision['size_multiplier']}")

        # Create Signal record for EVERY L1 PASS (shadow=True if rejected)
        try:
            from evaluator.tracker import create_signal
            create_signal(trade_context, decision, trade_params=None, executed=False)
        except Exception as e:
            logger.debug(f"Signal creation failed for {symbol}: {e}")

        # If approved, compute L3 trade parameters and attach to the just-saved DB record
        if decision['action'] == 'APPROVE':
            try:
                from executor.l3_calculator import L3Calculator
                strategy = trade_context.get('strategy', 'S1')
                params = L3Calculator().calculate(trade_context, decision, strategy=strategy)
                if params:
                    record = L2Decision.objects.filter(
                        symbol=symbol, action='APPROVE', trade_params__isnull=True
                    ).order_by('-timestamp').first()
                    if record:
                        record.trade_params = params
                        record.save(update_fields=['trade_params'])
                        logger.info(f"L3 params saved: {symbol} entry=${params['entry_price']:.0f} SL=${params['stop_loss']:.0f}")
            except Exception as e:
                logger.warning(f"L3 calc failed for {symbol}: {e}")

        return decision
    except Exception as e:
        logger.error(f"L2 task error {symbol}: {e}", exc_info=True)
        return {'action': 'REJECT', 'size_multiplier': 0.0, 'veto_reason': 'task_error'}
