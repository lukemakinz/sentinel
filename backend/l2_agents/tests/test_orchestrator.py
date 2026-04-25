"""Orchestrator tests — mock all 4 agents, verify L2Decision and DB save."""
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings

from l2_agents.base import AgentResponse
from l2_agents.orchestrator import L2Orchestrator
from l2_agents.models import L2Decision

TRADE_CONTEXT = {
    'symbol': 'BTCUSDT',
    'direction': 'LONG',
    'timestamp': '2026-04-24T08:00:00+00:00',
    'adx_value': 28.5,
    'funding_rate': 0.0003,
}

APPROVE = AgentResponse(verdict='APPROVE', confidence=75, reasoning='test')
REJECT  = AgentResponse(verdict='REJECT',  confidence=80, reasoning='test')
NEUTRAL = AgentResponse(verdict='NEUTRAL', confidence=50, reasoning='test')


def patch_all_agents(ct=APPROVE, ofq=APPROVE, rm=APPROVE, da=NEUTRAL):
    return [
        patch('l2_agents.orchestrator.ContextTraderAgent.analyze', return_value=ct),
        patch('l2_agents.orchestrator.OrderFlowQuantAgent.analyze', return_value=ofq),
        patch('l2_agents.orchestrator.RiskManagerAgent.analyze', return_value=rm),
        patch('l2_agents.orchestrator.DevilsAdvocateAgent.analyze', return_value=da),
    ]


@override_settings(ANTHROPIC_API_KEY='test-key')
class OrchestratorRunTest(TestCase):
    def setUp(self):
        self.orch = L2Orchestrator()

    def _run_with_patches(self, ct=APPROVE, ofq=APPROVE, rm=APPROVE, da=NEUTRAL):
        patches = patch_all_agents(ct, ofq, rm, da)
        for p in patches:
            p.start()
        try:
            return self.orch.run(TRADE_CONTEXT)
        finally:
            for p in patches:
                p.stop()

    def test_all_approve_returns_approve_decision(self):
        decision = self._run_with_patches()
        self.assertEqual(decision['action'], 'APPROVE')
        self.assertGreater(decision['size_multiplier'], 0)

    def test_risk_manager_reject_returns_reject_decision(self):
        decision = self._run_with_patches(rm=REJECT)
        self.assertEqual(decision['action'], 'REJECT')
        self.assertEqual(decision['size_multiplier'], 0.0)

    def test_decision_saved_to_db_on_approve(self):
        self._run_with_patches()
        self.assertEqual(L2Decision.objects.filter(symbol='BTCUSDT').count(), 1)
        db_record = L2Decision.objects.get(symbol='BTCUSDT')
        self.assertEqual(db_record.action, 'APPROVE')

    def test_decision_saved_to_db_on_reject(self):
        self._run_with_patches(rm=REJECT)
        self.assertEqual(L2Decision.objects.filter(symbol='BTCUSDT').count(), 1)
        db_record = L2Decision.objects.get(symbol='BTCUSDT')
        self.assertEqual(db_record.action, 'REJECT')

    def test_decision_contains_all_required_fields(self):
        decision = self._run_with_patches()
        for field in ('action', 'size_multiplier', 'agents_summary', 'symbol', 'direction'):
            self.assertIn(field, decision, f"Missing field: {field}")

    def test_agents_summary_has_all_four_agents(self):
        decision = self._run_with_patches()
        summary = decision['agents_summary']
        for agent in ('context_trader', 'order_flow_quant', 'risk_manager', 'devils_advocate'):
            self.assertIn(agent, summary, f"Missing agent in summary: {agent}")

    def test_run_not_called_without_api_key(self):
        with self.settings(ANTHROPIC_API_KEY=''):
            decision = self.orch.run(TRADE_CONTEXT)
        self.assertEqual(decision['action'], 'REJECT')
        self.assertEqual(decision.get('veto_reason'), 'no_api_key')

    def test_insufficient_approvals_returns_reject(self):
        decision = self._run_with_patches(ct=NEUTRAL, ofq=NEUTRAL, rm=APPROVE, da=NEUTRAL)
        self.assertEqual(decision['action'], 'REJECT')
