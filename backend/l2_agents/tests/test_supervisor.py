"""Supervisor logic is pure Python — no LLM mocking needed."""
from django.test import TestCase

from l2_agents.supervisor import L2Supervisor
from l2_agents.base import AgentResponse


def resp(verdict, confidence=60):
    return AgentResponse(verdict=verdict, confidence=confidence, reasoning='test')


class SupervisorVetoTest(TestCase):
    def setUp(self):
        self.sup = L2Supervisor()

    def _run(self, ct='APPROVE', ofq='APPROVE', rm='APPROVE', da='NEUTRAL', da_conf=50):
        return self.sup.evaluate({
            'context_trader':    resp(ct),
            'order_flow_quant':  resp(ofq),
            'risk_manager':      resp(rm),
            'devils_advocate':   resp(da, da_conf),
        })

    def test_risk_manager_reject_is_hard_veto(self):
        decision = self._run(rm='REJECT')
        self.assertEqual(decision['action'], 'REJECT')
        self.assertEqual(decision['size_multiplier'], 0.0)
        self.assertEqual(decision['veto_reason'], 'risk_manager')

    def test_three_approvals_give_full_size(self):
        decision = self._run(ct='APPROVE', ofq='APPROVE', rm='APPROVE', da='NEUTRAL')
        self.assertEqual(decision['action'], 'APPROVE')
        self.assertEqual(decision['size_multiplier'], 1.0)

    def test_two_approvals_give_75_percent(self):
        decision = self._run(ct='APPROVE', ofq='NEUTRAL', rm='APPROVE', da='NEUTRAL')
        self.assertEqual(decision['action'], 'APPROVE')
        self.assertEqual(decision['size_multiplier'], 0.75)

    def test_one_approval_is_rejected(self):
        decision = self._run(ct='APPROVE', ofq='NEUTRAL', rm='NEUTRAL', da='NEUTRAL')
        self.assertEqual(decision['action'], 'REJECT')

    def test_zero_approvals_is_rejected(self):
        decision = self._run(ct='REJECT', ofq='REJECT', rm='APPROVE', da='REJECT')
        # rm=APPROVE but ct,ofq,da all reject — only 1 approval (rm) → reject
        self.assertEqual(decision['action'], 'REJECT')

    def test_devils_advocate_high_confidence_halves_size(self):
        decision = self._run(ct='APPROVE', ofq='APPROVE', rm='APPROVE', da='REJECT', da_conf=80)
        self.assertEqual(decision['action'], 'APPROVE')
        self.assertEqual(decision['size_multiplier'], 0.5)

    def test_devils_advocate_low_confidence_no_penalty(self):
        decision = self._run(ct='APPROVE', ofq='APPROVE', rm='APPROVE', da='REJECT', da_conf=60)
        self.assertEqual(decision['action'], 'APPROVE')
        self.assertEqual(decision['size_multiplier'], 1.0)

    def test_decision_includes_agents_summary(self):
        decision = self._run()
        self.assertIn('agents_summary', decision)
        self.assertIn('context_trader', decision['agents_summary'])

    def test_all_approvals_four_agents(self):
        decision = self._run(ct='APPROVE', ofq='APPROVE', rm='APPROVE', da='APPROVE')
        self.assertEqual(decision['action'], 'APPROVE')
        self.assertEqual(decision['size_multiplier'], 1.0)
