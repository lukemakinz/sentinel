"""Deterministic supervisor — no LLM, pure logic."""
from .base import AgentResponse

DA_VETO_THRESHOLD = 70   # Devil's Advocate confidence above this → halve size
MIN_APPROVALS_FULL = 3   # ≥3 approvals → full size
MIN_APPROVALS_HALF = 2   # 2 approvals → 75% size (or 50% if DA vetoes)
AI_CORE_MIN_CONFIDENCE = 60


class L2Supervisor:
    def evaluate(self, responses: dict[str, AgentResponse], conservative: bool = False) -> dict:
        rm = responses.get('risk_manager')
        da = responses.get('devils_advocate')

        # Fail closed: risk approval is mandatory.  An unavailable/neutral risk
        # agent must never be out-voted by the narrative agents.
        if not rm or rm.verdict != 'APPROVE':
            reason = 'risk_manager' if rm and rm.verdict == 'REJECT' else 'risk_manager_unavailable'
            return self._decision('REJECT', 0.0, responses, veto_reason=reason)

        approvals = sum(1 for r in responses.values() if r.verdict == 'APPROVE')
        da_strong_reject = da and da.verdict == 'REJECT' and da.confidence >= DA_VETO_THRESHOLD

        if conservative:
            if da_strong_reject:
                return self._decision(
                    'REJECT', 0.0, responses, veto_reason='devils_advocate')
            core = ('context_trader', 'order_flow_quant', 'risk_manager')
            core_approved = all(
                responses.get(name)
                and responses[name].verdict == 'APPROVE'
                and responses[name].confidence >= AI_CORE_MIN_CONFIDENCE
                for name in core
            )
            if core_approved:
                # S12AI remains shadow-only.  The multiplier is retained only
                # for counterfactual sizing and must not authorize an order.
                return self._decision('APPROVE', 0.5, responses)
            return self._decision(
                'REJECT', 0.0, responses, veto_reason='conservative_ai_quorum')

        if approvals >= MIN_APPROVALS_FULL:
            multiplier = 0.5 if da_strong_reject else 1.0
            return self._decision('APPROVE', multiplier, responses)

        if approvals >= MIN_APPROVALS_HALF:
            multiplier = 0.5 if da_strong_reject else 0.75
            return self._decision('APPROVE', multiplier, responses)

        return self._decision('REJECT', 0.0, responses, veto_reason='insufficient_approval')

    @staticmethod
    def _decision(action: str, size: float, responses: dict, veto_reason: str = '') -> dict:
        summary = {
            name: {'verdict': r.verdict, 'confidence': r.confidence, 'reasoning': r.reasoning}
            for name, r in responses.items()
        }
        result = {
            'action': action,
            'size_multiplier': size,
            'agents_summary': summary,
        }
        if veto_reason:
            result['veto_reason'] = veto_reason
        return result
