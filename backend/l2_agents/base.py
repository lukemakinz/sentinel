"""Shared base for all L2 AI agents.

Provider priority:
  1. Anthropic Claude Haiku  — if ANTHROPIC_API_KEY is set
  2. OpenAI GPT-4o-mini      — if OPENAI_API_KEY is set
  Both set → Anthropic preferred (better instruction-following for structured JSON).
"""
import json
import logging
from typing import Literal

from django.conf import settings
from pydantic import BaseModel

logger = logging.getLogger(__name__)

ANTHROPIC_MODEL = 'claude-haiku-4-5'
OPENAI_MODEL    = 'gpt-4o-mini'


class AgentResponse(BaseModel):
    verdict:    Literal['APPROVE', 'REJECT', 'NEUTRAL']
    confidence: int   # 0–100
    reasoning:  str


NEUTRAL_ERROR = AgentResponse(
    verdict='NEUTRAL', confidence=10,
    reasoning='Agent error — defaulting to NEUTRAL'
)


def _active_provider() -> str | None:
    """Returns 'anthropic', 'openai', or None."""
    if getattr(settings, 'ANTHROPIC_API_KEY', ''):
        return 'anthropic'
    if getattr(settings, 'OPENAI_API_KEY', ''):
        return 'openai'
    return None


class BaseAgent:
    system_prompt: str = ''

    def analyze(self, trade_context: dict) -> AgentResponse:
        provider = _active_provider()
        if not provider:
            logger.warning(f"{self.__class__.__name__}: no API key — returning NEUTRAL")
            return NEUTRAL_ERROR
        try:
            if provider == 'anthropic':
                return self._call_anthropic(trade_context)
            return self._call_openai(trade_context)
        except Exception as e:
            logger.error(f"{self.__class__.__name__} [{provider}] error: {e}", exc_info=True)
            return NEUTRAL_ERROR

    # ── Anthropic ─────────────────────────────────────────────────────────────

    def _call_anthropic(self, trade_context: dict) -> AgentResponse:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        user_msg = self._build_user_message(trade_context)

        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=[{
                'type': 'text',
                'text': self.system_prompt,
                'cache_control': {'type': 'ephemeral'},
            }],
            tools=[{
                'name': 'submit_verdict',
                'description': 'Submit your structured analysis verdict.',
                'input_schema': AgentResponse.model_json_schema(),
            }],
            tool_choice={'type': 'tool', 'name': 'submit_verdict'},
            messages=[{'role': 'user', 'content': user_msg}],
        )

        for block in response.content:
            if block.type == 'tool_use' and block.name == 'submit_verdict':
                return AgentResponse(**block.input)

        raise ValueError(f"No tool_use block from Anthropic: {response.content}")

    # ── OpenAI ────────────────────────────────────────────────────────────────

    def _call_openai(self, trade_context: dict) -> AgentResponse:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        user_msg = self._build_user_message(trade_context)

        schema = AgentResponse.model_json_schema()
        schema['additionalProperties'] = False   # required for strict mode

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {'role': 'system', 'content': self.system_prompt},
                {'role': 'user',   'content': user_msg},
            ],
            tools=[{
                'type': 'function',
                'function': {
                    'name':        'submit_verdict',
                    'description': 'Submit your structured analysis verdict.',
                    'parameters':  schema,
                    'strict':      True,
                },
            }],
            tool_choice={'type': 'function', 'function': {'name': 'submit_verdict'}},
            max_tokens=1024,
        )

        tool_call = response.choices[0].message.tool_calls[0]
        return AgentResponse(**json.loads(tool_call.function.arguments))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_user_message(self, ctx: dict) -> str:
        return (
            f"Analyze this {ctx.get('direction', 'UNKNOWN')} setup on {ctx.get('symbol', 'UNKNOWN')}.\n\n"
            f"TradeContext:\n{self._format_context(ctx)}\n\n"
            f"Return your verdict as structured JSON."
        )

    @staticmethod
    def _format_context(ctx: dict) -> str:
        return '\n'.join(
            f"  {k}: {v}"
            for k, v in ctx.items()
            if k != 'timestamp'
        )
