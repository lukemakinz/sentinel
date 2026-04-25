"""Deterministic supervisor — no LLM, pure logic."""
from .base import AgentResponse

DA_VETO_THRESHOLD = 70   # Devil's Advocate confidence above this → halve size
MIN_APPROVALS_FULL = 3   # ≥3 approvals → full size
MIN_APPROVALS_HALF = 2   # 2 approvals → 75% size (or 50% if DA vetoes)


class L2Supervisor:
    def evaluate(self, responses: dict[str, AgentResponse]) -> dict:
        rm = responses.get('risk_manager')
        da = responses.get('devils_advocate')

        # Hard veto: Risk Manager always wins
        if rm and rm.verdict == 'REJECT':
            return self._decision('REJECT', 0.0, responses, veto_reason='risk_manager')

        approvals = sum(1 for r in responses.values() if r.verdict == 'APPROVE')
        da_strong_reject = da and da.verdict == 'REJECT' and da.confidence >= DA_VETO_THRESHOLD

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
