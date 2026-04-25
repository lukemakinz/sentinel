"""Agent tests — mock at _call_anthropic / _call_openai level, verify schema and prompts."""
from unittest.mock import patch
from django.test import TestCase, override_settings

from l2_agents.base import AgentResponse, NEUTRAL_ERROR
from l2_agents.context_trader import ContextTraderAgent
from l2_agents.order_flow_quant import OrderFlowQuantAgent
from l2_agents.risk_manager_agent import RiskManagerAgent
from l2_agents.devils_advocate import DevilsAdvocateAgent

TRADE_CONTEXT = {
    'symbol': 'BTCUSDT',
    'timestamp': '2026-04-24T08:00:00+00:00',
    'direction': 'LONG',
    'adx_value': 28.5,
    'funding_rate': 0.0003,
    'atr': 450.0,
    'fvg_zone': [93200, 93800],
    'swept_level': 92800.0,
    'btc_trend': 'bullish',
    'regime': 'trending',
}

APPROVE = AgentResponse(verdict='APPROVE', confidence=75, reasoning='Strong setup')
REJECT  = AgentResponse(verdict='REJECT',  confidence=80, reasoning='No structure')
NEUTRAL = AgentResponse(verdict='NEUTRAL', confidence=50, reasoning='Ambiguous')


def mock_call(response: AgentResponse):
    """Patch _call_anthropic OR _call_openai to return a fixed AgentResponse."""
    return patch.multiple(
        'l2_agents.base.BaseAgent',
        _call_anthropic=lambda self, ctx: response,
        _call_openai=lambda self, ctx: response,
    )


@override_settings(ANTHROPIC_API_KEY='test-key', OPENAI_API_KEY='')
class ContextTraderAgentTest(TestCase):
    def setUp(self):
        self.agent = ContextTraderAgent()

    def test_returns_approve(self):
        with mock_call(APPROVE):
            result = self.agent.analyze(TRADE_CONTEXT)
        self.assertEqual(result.verdict, 'APPROVE')
        self.assertEqual(result.confidence, 75)

    def test_returns_reject(self):
        with mock_call(REJECT):
            result = self.agent.analyze(TRADE_CONTEXT)
        self.assertEqual(result.verdict, 'REJECT')

    def test_returns_neutral_on_error(self):
        with patch.object(self.agent, '_call_anthropic', side_effect=Exception('API down')):
            result = self.agent.analyze(TRADE_CONTEXT)
        self.assertEqual(result.verdict, 'NEUTRAL')
        self.assertLess(result.confidence, 30)

    def test_system_prompt_forbids_entry_numbers(self):
        prompt = self.agent.system_prompt.lower()
        self.assertTrue(
            any(kw in prompt for kw in ['do not', "don't", 'never', 'forbidden', 'prohibit']),
            "System prompt must restrict number generation"
        )

    def test_no_key_returns_neutral(self):
        with self.settings(ANTHROPIC_API_KEY='', OPENAI_API_KEY=''):
            result = self.agent.analyze(TRADE_CONTEXT)
        self.assertEqual(result.verdict, 'NEUTRAL')

    def test_openai_fallback_used_when_no_anthropic(self):
        with self.settings(ANTHROPIC_API_KEY='', OPENAI_API_KEY='openai-test-key'):
            with mock_call(APPROVE):
                result = self.agent.analyze(TRADE_CONTEXT)
        self.assertEqual(result.verdict, 'APPROVE')


@override_settings(ANTHROPIC_API_KEY='test-key', OPENAI_API_KEY='')
class OrderFlowQuantAgentTest(TestCase):
    def test_returns_valid_response(self):
        with mock_call(APPROVE):
            result = OrderFlowQuantAgent().analyze(TRADE_CONTEXT)
        self.assertIn(result.verdict, ('APPROVE', 'REJECT', 'NEUTRAL'))

    def test_error_returns_neutral(self):
        agent = OrderFlowQuantAgent()
        with patch.object(agent, '_call_anthropic', side_effect=Exception('timeout')):
            result = agent.analyze(TRADE_CONTEXT)
        self.assertEqual(result.verdict, 'NEUTRAL')


@override_settings(ANTHROPIC_API_KEY='test-key', OPENAI_API_KEY='')
class RiskManagerAgentTest(TestCase):
    def test_approve(self):
        with mock_call(APPROVE):
            result = RiskManagerAgent().analyze(TRADE_CONTEXT)
        self.assertEqual(result.verdict, 'APPROVE')

    def test_reject_on_risky_context(self):
        with mock_call(REJECT):
            result = RiskManagerAgent().analyze({**TRADE_CONTEXT, 'funding_rate': 0.002})
        self.assertEqual(result.verdict, 'REJECT')


@override_settings(ANTHROPIC_API_KEY='test-key', OPENAI_API_KEY='')
class DevilsAdvocateAgentTest(TestCase):
    def test_returns_valid_response(self):
        with mock_call(NEUTRAL):
            result = DevilsAdvocateAgent().analyze(TRADE_CONTEXT)
        self.assertIn(result.verdict, ('APPROVE', 'REJECT', 'NEUTRAL'))

    def test_system_prompt_is_contrarian(self):
        prompt = DevilsAdvocateAgent().system_prompt.lower()
        self.assertTrue(
            any(kw in prompt for kw in ['contrarian', 'against', 'devil', 'fail', 'risk', 'wrong']),
            "Devil's Advocate prompt must be contrarian"
        )


@override_settings(ANTHROPIC_API_KEY='', OPENAI_API_KEY='openai-key')
class OpenAIProviderTest(TestCase):
    """Verify OpenAI path is used when only OPENAI_API_KEY is set."""

    def test_openai_provider_selected(self):
        from l2_agents.base import _active_provider
        with self.settings(ANTHROPIC_API_KEY='', OPENAI_API_KEY='sk-test'):
            self.assertEqual(_active_provider(), 'openai')

    def test_anthropic_preferred_when_both_set(self):
        from l2_agents.base import _active_provider
        with self.settings(ANTHROPIC_API_KEY='ant-key', OPENAI_API_KEY='sk-test'):
            self.assertEqual(_active_provider(), 'anthropic')

    def test_none_when_no_keys(self):
        from l2_agents.base import _active_provider
        with self.settings(ANTHROPIC_API_KEY='', OPENAI_API_KEY=''):
            self.assertIsNone(_active_provider())
