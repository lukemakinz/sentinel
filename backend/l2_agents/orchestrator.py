"""L2Orchestrator: runs 4 agents concurrently, passes to Supervisor, saves L2Decision."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings

from .base import AgentResponse
from .context_trader import ContextTraderAgent
from .order_flow_quant import OrderFlowQuantAgent
from .risk_manager_agent import RiskManagerAgent
from .devils_advocate import DevilsAdvocateAgent
from .supervisor import L2Supervisor
from .models import L2Decision

logger = logging.getLogger(__name__)

_AGENTS = {
    'context_trader':   ContextTraderAgent,
    'order_flow_quant': OrderFlowQuantAgent,
    'risk_manager':     RiskManagerAgent,
    'devils_advocate':  DevilsAdvocateAgent,
}


class L2Orchestrator:
    def __init__(self):
        self.supervisor = L2Supervisor()

    def run(self, trade_context: dict) -> dict:
        symbol    = trade_context.get('symbol', '')
        direction = trade_context.get('direction', '')

        if not settings.ANTHROPIC_API_KEY:
            logger.warning("L2 skipped — no ANTHROPIC_API_KEY")
            decision = {'action': 'REJECT', 'size_multiplier': 0.0,
                        'veto_reason': 'no_api_key', 'agents_summary': {},
                        'symbol': symbol, 'direction': direction}
            self._save(symbol, direction, decision, trade_context)
            return decision

        responses = self._run_agents_parallel(trade_context)
        decision  = self.supervisor.evaluate(responses)
        decision.update({'symbol': symbol, 'direction': direction})

        self._save(symbol, direction, decision, trade_context)
        return decision

    def _run_agents_parallel(self, trade_context: dict) -> dict[str, AgentResponse]:
        results = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(agent_cls().analyze, trade_context): name
                for name, agent_cls in _AGENTS.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception as e:
                    logger.error(f"Agent {name} failed: {e}", exc_info=True)
                    from .base import NEUTRAL_ERROR
                    results[name] = NEUTRAL_ERROR
        return results

    @staticmethod
    def _save(symbol: str, direction: str, decision: dict, trade_context: dict):
        L2Decision.objects.create(
            symbol=symbol,
            direction=direction,
            action=decision.get('action', 'REJECT'),
            size_multiplier=decision.get('size_multiplier', 0.0),
            veto_reason=decision.get('veto_reason', ''),
            agents_summary=decision.get('agents_summary', {}),
            trade_context=trade_context,
        )
