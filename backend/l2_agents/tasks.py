"""Celery task: run L2 analysis when L1 passes."""
import logging
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(name='l2_agents.run_auction_shadow_cycle')
def run_auction_shadow_cycle() -> dict:
    """Run at most one immutable shadow adjudication per closed 15m bar."""
    if not getattr(settings, 'AUCTION_SHADOW_ENABLED', True):
        return {'disabled': True}
    from risk.models import system_paused
    if system_paused():
        return {'paused': True}

    from ingester.models import WatchedPair
    from .auction_adjudicator import summarize_analysis_costs
    from .auction_service import analyze_symbol

    use_ai = bool(getattr(settings, 'AUCTION_SHADOW_AI_ENABLED', False))
    results = {'created': 0, 'deduplicated': 0, 'actions': {}, 'errors': {}}
    costs = []
    for symbol in WatchedPair.get_active_symbols():
        try:
            output = analyze_symbol(
                symbol, use_ai=use_ai, persist=True, deduplicate_bar=True,
                baseline=True,
            )
            bucket = 'created' if output['created'] else 'deduplicated'
            results[bucket] += 1
            action = output['decision']['action']
            results['actions'][action] = results['actions'].get(action, 0) + 1
            costs.append(output['analysis_cost'])
        except Exception as exc:
            logger.error('Auction shadow cycle failed for %s: %s', symbol, exc, exc_info=True)
            results['errors'][symbol] = type(exc).__name__
    # Deliberately last: every cycle reports what it spent.
    results['analysis_cost'] = summarize_analysis_costs(costs)
    logger.info(
        'Auction shadow cycle: %s created, %s deduplicated, cost %s',
        results['created'], results['deduplicated'],
        results['analysis_cost']['display'],
    )
    return results


@shared_task(name='l2_agents.resolve_auction_shadow_plans')
def resolve_auction_shadow_plans() -> dict:
    """Advance armed plans from closed candles; never submits an order."""
    from .shadow_auction import resolve_open_plans
    return resolve_open_plans()


@shared_task(name='l2_agents.run_l2_analysis')
def run_l2_analysis(trade_context: dict) -> dict:
    """Run L2 agents → if APPROVE, run L3 Calculator and save trade params."""
    from .orchestrator import L2Orchestrator
    from .models import L2Decision
    symbol = trade_context.get('symbol', '?')
    try:
        decision = L2Orchestrator().run(trade_context)
        logger.info(f"L2 {symbol}: {decision['action']} ×{decision['size_multiplier']}")

        params = None
        # Compute counterfactual geometry even for rejected candidates.  This
        # makes APPROVE vs REJECT measurable in shadow evaluation.  It does not
        # place an order.
        try:
            from executor.l3_calculator import L3Calculator
            strategy = trade_context.get('strategy', 'S1')
            geometry_decision = decision if decision['action'] == 'APPROVE' else {
                'action': 'APPROVE', 'size_multiplier': 1.0,
            }
            params = L3Calculator().calculate(
                trade_context, geometry_decision, strategy=strategy)
            if params and decision['action'] == 'APPROVE':
                ai_execution_locked = (
                    strategy == 'S12AI'
                    and not getattr(settings, 'AI_ADJUDICATOR_EXECUTION_ENABLED', False)
                )
                if trade_context.get('shadow_only') or ai_execution_locked:
                    logger.info(f"L3 shadow params calculated for {symbol}; execution locked")
                else:
                    record = L2Decision.objects.filter(
                        symbol=symbol, action='APPROVE', trade_params__isnull=True
                    ).order_by('-timestamp').first()
                    if record:
                        record.trade_params = params
                        record.save(update_fields=['trade_params'])
                        logger.info(f"L3 params saved: {symbol} entry=${params['entry_price']:.0f} SL=${params['stop_loss']:.0f}")
        except Exception as e:
            logger.warning(f"L3 calc failed for {symbol}: {e}")

        # Create a shadow Signal for every decision, including rejections, with
        # identical counterfactual geometry whenever it was calculable.
        try:
            from evaluator.tracker import create_signal
            create_signal(trade_context, decision, trade_params=params, executed=False)
        except Exception as e:
            logger.debug(f"Signal creation failed for {symbol}: {e}")

        return decision
    except Exception as e:
        logger.error(f"L2 task error {symbol}: {e}", exc_info=True)
        return {'action': 'REJECT', 'size_multiplier': 0.0, 'veto_reason': 'task_error'}
