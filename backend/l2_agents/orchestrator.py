"""L2Orchestrator: runs 4 agents concurrently, passes to Supervisor, saves L2Decision."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings

from .base import (
    AI_PROMPT_VERSION, ANTHROPIC_MODEL, OPENAI_MODEL,
    AgentResponse, _active_provider,
)
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

        provider = _active_provider()
        if not provider:
            logger.warning("L2 skipped — no supported AI provider key")
            decision = {'action': 'REJECT', 'size_multiplier': 0.0,
                        'veto_reason': 'no_api_key', 'agents_summary': {},
                        'symbol': symbol, 'direction': direction}
            self._save(symbol, direction, decision, trade_context)
            return decision

        trade_context = {
            **trade_context,
            'risk_snapshot': self._risk_snapshot(),
            'ai_runtime': {
                'provider': provider,
                'model': ANTHROPIC_MODEL if provider == 'anthropic' else OPENAI_MODEL,
                'prompt_version': AI_PROMPT_VERSION,
            },
        }
        responses = self._run_agents_parallel(trade_context)
        decision  = self.supervisor.evaluate(
            responses,
            conservative=trade_context.get('strategy') == 'S12AI',
        )
        decision.update({'symbol': symbol, 'direction': direction})

        self._save(symbol, direction, decision, trade_context)
        return decision

    @staticmethod
    def _risk_snapshot() -> dict:
        """Read-only portfolio facts for the AI risk role; never creates state."""
        try:
            from risk.models import RiskState
            from executor.models import AccountState, Position

            state = RiskState.objects.filter(pk=1).first()
            account = AccountState.objects.order_by('-updated_at').first()
            return {
                'available': bool(state or account),
                'daily_pnl_pct': float(state.daily_pnl) if state else None,
                'weekly_pnl_pct': float(state.weekly_pnl) if state else None,
                'consecutive_losses': int(state.consecutive_losses) if state else None,
                'daily_stopped': bool(state.is_daily_stopped) if state else None,
                'weekly_stopped': bool(state.is_weekly_stopped) if state else None,
                'position_size_multiplier': float(state.position_size_multiplier) if state else None,
                'open_positions': Position.objects.filter(status='OPEN').count(),
                'equity_usd': float(account.equity) if account else None,
            }
        except Exception as exc:
            logger.warning(f'Risk snapshot unavailable: {exc}')
            return {'available': False, 'error': 'risk_snapshot_unavailable'}

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
        ai_execution_locked = (
            trade_context.get('strategy') == 'S12AI'
            and not getattr(settings, 'AI_ADJUDICATOR_EXECUTION_ENABLED', False)
        )
        L2Decision.objects.create(
            symbol=symbol,
            direction=direction,
            action=decision.get('action', 'REJECT'),
            size_multiplier=decision.get('size_multiplier', 0.0),
            veto_reason=decision.get('veto_reason', ''),
            agents_summary=decision.get('agents_summary', {}),
            trade_context=trade_context,
            dismissed=bool(trade_context.get('shadow_only') or ai_execution_locked),
        )
