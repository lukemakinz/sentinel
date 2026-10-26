"""AI adjudication for S20-style candidates: gpt-4o-mini (same model
already used elsewhere in this codebase — see l2_agents/base.py) receives
ONLY anonymized, normalized technical readings — no symbol name, no date,
no raw price — and independently decides LONG / SHORT / PASS.

Deliberately anonymized so this CAN be run retrospectively: the leakage
risk this project has always flagged for AI backtesting (the model may
have seen a specific historical period for a named symbol during its own
training) is greatly reduced when the model is never told which symbol or
date it is looking at, only relative numbers. This is a mitigation, not a
guarantee — the model could still pattern-match on generic setup shapes —
and is disclosed as such in every report this module contributes to.

Every call's token usage is recorded so total cost is known, not guessed.
"""
import json
import logging

from decouple import config
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

OPENAI_MODEL = 'gpt-4o-mini'
# Published per-1M-token list price for gpt-4o-mini, USD. Used only to
# report an estimated cost; the actual bill may differ (batch discounts,
# rate changes, etc.) — always disclosed as an estimate, not an invoice.
PRICE_PER_1M_INPUT_USD = 0.150
PRICE_PER_1M_OUTPUT_USD = 0.600

SYSTEM_PROMPT = """You are a disciplined, risk-focused crypto derivatives trader. You will be shown ONLY a set of anonymized, normalized technical readings for one candidate moment — never a symbol name, date, or raw price. Decide independently: LONG, SHORT, or PASS.

Field meanings:
- adx: 1h ADX(14) trend-strength reading on the higher timeframe (0-100+, >20 is usually considered trending).
- regime: "up" or "down" — the pre-computed 4h trend direction this candidate was drawn from (you may agree or disagree with trading it).
- obv_diff_for_regime_direction: on-balance-volume minus its own EMA(9), signed so that POSITIVE means volume flow agrees with `regime`'s direction.
- cvd_diff_for_regime_direction: cumulative volume delta (actual taker buy/sell volume) minus its own EMA(9), same sign convention as obv_diff.
- oi_change_for_regime_direction: open interest change over the prior 8 bars (2h), same sign convention — positive means new positioning is building in `regime`'s direction, not just short-covering.
- rsi_for_regime_direction: RSI(14), reoriented so higher values always favor `regime`'s direction (i.e. this is 100-RSI when regime is "down").
- displacement_atr: how many multiples of ATR the structural displacement candle moved (this candidate's institutional order-block strength; higher = stronger footprint).
- atr_pct: ATR as a percentage of price (volatility regime — very high values mean unusually choppy/wide conditions).
- recent_candles_pct: the last several closed bars' percentage moves (close-to-close), most recent last — the raw recent shape of price action, with no absolute price attached.

A purely mechanical filter already required regime alignment, ADX>=20, OBV and OI both agreeing with `regime`'s direction, and a real order-block displacement before generating this candidate — so every candidate you see already cleared that bar. Historical evidence shows that raw mechanical queue is only marginally profitable after trading costs, so do not simply agree with `regime` by default: only pick LONG or SHORT (in `regime`'s direction or against it) when the specific numbers give you genuine conviction, and PASS whenever the picture looks mixed, overextended, or unremarkable. A missed trade costs nothing; a bad one costs real money.

Respond with strict JSON via the submit_verdict tool only."""


class AIVerdict(BaseModel):
    verdict: str = Field(description="Exactly one of 'LONG', 'SHORT', 'PASS'")
    confidence: float = Field(description='0.0 to 1.0')
    reasoning: str = Field(description='One or two sentences, specific to the numbers shown')


def adjudicate(candidate_context: dict) -> tuple[dict, dict]:
    """Ask gpt-4o-mini for an independent LONG/SHORT/PASS verdict on an
    anonymized candidate. Returns (verdict_dict, usage_dict). Raises on any
    API/parsing failure — callers must treat a failure as PASS (never
    silently trade on an error)."""
    from openai import OpenAI

    client = OpenAI(api_key=config('OPENAI_API_KEY'))
    schema = AIVerdict.model_json_schema()
    schema['additionalProperties'] = False

    user_message = (
        f"Candidate readings:\n{json.dumps(candidate_context, indent=2, default=str)}\n\n"
        "Return your verdict as structured JSON."
    )
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_message},
        ],
        tools=[{
            'type': 'function',
            'function': {
                'name': 'submit_verdict',
                'description': 'Submit your structured LONG/SHORT/PASS verdict.',
                'parameters': schema,
                'strict': True,
            },
        }],
        tool_choice={'type': 'function', 'function': {'name': 'submit_verdict'}},
        max_tokens=512,
    )
    tool_call = response.choices[0].message.tool_calls[0]
    verdict = AIVerdict(**json.loads(tool_call.function.arguments))
    if verdict.verdict not in ('LONG', 'SHORT', 'PASS'):
        raise ValueError(f'Unexpected verdict value: {verdict.verdict}')

    usage = response.usage
    usage_dict = {
        'prompt_tokens': usage.prompt_tokens,
        'completion_tokens': usage.completion_tokens,
        'cost_usd': (usage.prompt_tokens / 1_000_000 * PRICE_PER_1M_INPUT_USD
                    + usage.completion_tokens / 1_000_000 * PRICE_PER_1M_OUTPUT_USD),
    }
    return verdict.model_dump(), usage_dict
