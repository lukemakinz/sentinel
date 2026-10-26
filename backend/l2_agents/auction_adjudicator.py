"""Shadow-only, structured adjudicator for auction-state trade candidates."""
from __future__ import annotations

import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from django.conf import settings
from pydantic import BaseModel, Field

from .base import ANTHROPIC_MODEL
from .market_intelligence import deterministic_preflight

logger = logging.getLogger(__name__)

AUCTION_PROMPT_VERSION = 'sentinel-auction-adjudicator-v1'
OPENAI_PRICING_REFERENCE = 'https://developers.openai.com/api/docs/pricing'


class AdjudicationError(Exception):
    """A provider response was billed but could not be accepted."""

    def __init__(self, message: str, usage: dict):
        super().__init__(message)
        self.usage = usage


def zero_analysis_cost(reason: str) -> dict:
    return {
        'status': 'not_billed',
        'currency': 'USD',
        'estimated_usd': 0.0,
        'display': '$0.00000000 USD',
        'reason': reason,
    }


def unavailable_analysis_cost(reason: str) -> dict:
    return {
        'status': 'unavailable',
        'currency': 'USD',
        'estimated_usd': None,
        'display': 'unavailable',
        'reason': reason,
    }


def summarize_analysis_costs(costs) -> dict:
    """Summarize known per-analysis costs without hiding unavailable items."""
    costs = list(costs)
    known = [
        cost for cost in costs
        if cost and cost.get('estimated_usd') is not None
    ]
    unavailable = len(costs) - len(known)
    total = sum(
        (Decimal(str(cost['estimated_usd'])) for cost in known),
        Decimal('0'),
    ).quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP)
    if not costs:
        status = 'not_billed'
    elif unavailable == 0:
        status = 'complete'
    elif known:
        status = 'partial'
    else:
        status = 'unavailable'
    display = (
        f'${total:.8f} USD'
        if unavailable == 0
        else f'${total:.8f} USD known + {unavailable} unavailable'
    )
    return {
        'status': status,
        'currency': 'USD',
        'estimated_usd_known': float(total),
        'display': display,
        'analyses_total': len(costs),
        'analyses_with_known_cost': len(known),
        'analyses_with_unavailable_cost': unavailable,
    }


def estimate_openai_analysis_cost(*, model: str, input_tokens: int,
                                  output_tokens: int,
                                  cached_input_tokens: int = 0) -> dict:
    """Estimate one response from actual usage at configured Standard rates."""
    input_tokens = max(int(input_tokens or 0), 0)
    output_tokens = max(int(output_tokens or 0), 0)
    cached_input_tokens = min(max(int(cached_input_tokens or 0), 0), input_tokens)
    uncached_input_tokens = input_tokens - cached_input_tokens

    input_rate = Decimal(str(getattr(
        settings, 'AUCTION_OPENAI_INPUT_USD_PER_MILLION', 2.0,
    )))
    cached_rate = Decimal(str(getattr(
        settings, 'AUCTION_OPENAI_CACHED_INPUT_USD_PER_MILLION', 0.10,
    )))
    output_rate = Decimal(str(getattr(
        settings, 'AUCTION_OPENAI_OUTPUT_USD_PER_MILLION', 10.0,
    )))
    pricing_tier = 'standard_short_context'
    # GPT-6.1 Sol prices the full request above 272K input at 2x input/cache
    # and 1.5x output. Auction snapshots are normally far below this boundary.
    if input_tokens > 272_000:
        input_rate *= Decimal('2')
        cached_rate *= Decimal('2')
        output_rate *= Decimal('1.5')
        pricing_tier = 'standard_long_context'

    million = Decimal('1000000')
    estimated = (
        Decimal(uncached_input_tokens) * input_rate
        + Decimal(cached_input_tokens) * cached_rate
        + Decimal(output_tokens) * output_rate
    ) / million
    estimated = estimated.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP)
    return {
        'status': 'estimated',
        'currency': 'USD',
        'estimated_usd': float(estimated),
        'display': f'${estimated:.8f} USD',
        'model': model,
        'input_tokens': input_tokens,
        'cached_input_tokens': cached_input_tokens,
        'uncached_input_tokens': uncached_input_tokens,
        'output_tokens': output_tokens,
        'pricing_tier': pricing_tier,
        'rates_usd_per_million': {
            'uncached_input': float(input_rate),
            'cached_input': float(cached_rate),
            'output': float(output_rate),
        },
        'pricing_as_of': getattr(
            settings, 'AUCTION_OPENAI_PRICING_AS_OF', '2026-10-26',
        ),
        'pricing_reference': OPENAI_PRICING_REFERENCE,
    }

SYSTEM_PROMPT = """You are Sentinel's senior market-state adjudicator for crypto perpetual futures. You are not a price oracle and you are not allowed to execute orders. Your job is to decide whether a mechanically generated market snapshot should be PASSed, WAITed on, or ARMed for a later deterministic trigger.

Hard rules:
1. Use only facts in the supplied snapshot. Never invent a level, indicator, event, order-book wall, liquidation cluster, or market narrative.
2. Missing, stale, internally inconsistent, or low-quality data requires PASS. Confidence cannot compensate for missing data.
3. AIO measures attention/intensity, not direction. High AIO alone is never a long or short signal.
4. Order-book liquidity can be cancelled or spoofed. Treat imbalance as confluence only; persistent price structure and executed flow take priority.
5. Liquidation observations are executed events, not a ground-truth map of future liquidations.
6. OBV, volume and CVD are correlated evidence. Do not count them as three independent confirmations.
7. Choose only a strategy whose registry status is SHADOW_ONLY. Never propose an unlisted strategy.
8. ARM requires: a supplied zone, a precise future trigger, a precise invalidation, acceptable data quality, and agreement between global regime and the proposed setup unless the selected strategy explicitly models a failed auction.
9. WAIT means the thesis is plausible but the required trigger has not occurred. PASS means the setup is invalid, untradeable, stale, too ambiguous, or lacks reward space.
10. Never output ENTER, order size, leverage, or permission to trade. Risk and execution remain deterministic and locked.
11. Examine both long and short explanations. State the strongest counter-thesis. Prefer PASS over a weak story.
12. Stop management must be one of the supplied policy IDs. P0 is the default. Do not select breakeven merely because price moved in favor; it requires a separately validated policy.
13. For ARM, entry_zone must exactly copy the low/high of one supplied snapshot zone. Do not round or create a nearby zone. IFVG_FLIP must select an FVG zone. A long failed-auction or trend-retest setup must use support/FVG; a short setup must use resistance/FVG.

Return a single structured decision through the required tool. Keep evidence concise and tied to named snapshot fields."""


class AuctionDecision(BaseModel):
    action: Literal['PASS', 'WAIT', 'ARM']
    direction: Literal['LONG', 'SHORT', 'NONE']
    strategy_id: Literal[
        'SAI1_FAILED_AUCTION', 'SAI1_IFVG_FLIP', 'SAI1_TREND_RETEST', 'NONE',
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    data_quality: float = Field(ge=0.0, le=1.0)
    thesis: list[str]
    counter_thesis: list[str]
    entry_zone: list[float] | None
    trigger_conditions: list[str]
    invalidation_conditions: list[str]
    management_policy: Literal[
        'P0_INITIAL_STOP', 'P1_STRUCTURAL', 'P2_HYBRID', 'NONE',
    ]
    ttl_minutes: int = Field(ge=0, le=240)
    recheck_condition: str
    risk_notes: list[str]


class AuctionAdjudicator:
    """Calls one model once; deterministic validation remains the authority."""

    @staticmethod
    def _provider() -> str | None:
        """Resolve the Auction provider independently from legacy L2 agents."""
        provider = getattr(settings, 'AUCTION_AI_PROVIDER', 'openai').lower()
        if provider == 'openai' and getattr(settings, 'OPENAI_API_KEY', ''):
            return 'openai'
        if provider == 'anthropic' and getattr(settings, 'ANTHROPIC_API_KEY', ''):
            return 'anthropic'
        return None

    def analyze(self, snapshot: dict) -> tuple[AuctionDecision, dict]:
        preflight = deterministic_preflight(snapshot)
        if preflight['action'] == 'PASS':
            return AuctionDecision(**preflight), {
                'provider': None, 'model': None, 'prompt_version': AUCTION_PROMPT_VERSION,
                'reason': 'deterministic_preflight_reject',
                'analysis_cost': zero_analysis_cost('no_api_call'),
            }

        provider = self._provider()
        if provider is None:
            no_provider = {
                **preflight,
                'action': 'PASS',
                'counter_thesis': ['No configured AI provider; fail closed.'],
                'recheck_condition': 'Configure a supported provider and rerun in shadow mode.',
                'risk_notes': ['AI unavailable; execution remains locked.'],
            }
            return AuctionDecision(**no_provider), {
                'provider': None, 'model': None, 'prompt_version': AUCTION_PROMPT_VERSION,
                'reason': 'no_api_key',
                'analysis_cost': zero_analysis_cost('no_api_call'),
            }

        if provider == 'anthropic':
            decision, usage = self._call_anthropic(snapshot)
            model = ANTHROPIC_MODEL
        else:
            decision, usage = self._call_openai(snapshot)
            model = getattr(settings, 'AUCTION_OPENAI_MODEL', 'gpt-6.1-sol')

        if 'analysis_cost' not in usage:
            usage['analysis_cost'] = unavailable_analysis_cost(
                f'pricing_not_configured_for_{provider}',
            )

        try:
            self._validate_against_snapshot(decision, snapshot)
        except ValueError as exc:
            raise AdjudicationError(str(exc), {
                'provider': provider, 'model': model, **usage,
            }) from exc
        runtime = {
            'provider': provider,
            'model': model,
            'prompt_version': AUCTION_PROMPT_VERSION,
            **usage,
        }
        return decision, runtime

    @staticmethod
    def _message(snapshot: dict) -> str:
        return (
            "Adjudicate this immutable market snapshot. Execution is locked.\n\n"
            f"{json.dumps(snapshot, sort_keys=True, indent=2, default=str)}"
        )

    def _call_anthropic(self, snapshot: dict) -> tuple[AuctionDecision, dict]:
        import anthropic

        response = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY).messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1600,
            system=SYSTEM_PROMPT,
            tools=[{
                'name': 'submit_auction_decision',
                'description': 'Submit the shadow auction-state decision.',
                'input_schema': AuctionDecision.model_json_schema(),
            }],
            tool_choice={'type': 'tool', 'name': 'submit_auction_decision'},
            messages=[{'role': 'user', 'content': self._message(snapshot)}],
        )
        usage = getattr(response, 'usage', None)
        usage = {
            'input_tokens': getattr(usage, 'input_tokens', None),
            'output_tokens': getattr(usage, 'output_tokens', None),
        }
        for block in response.content:
            if block.type == 'tool_use' and block.name == 'submit_auction_decision':
                try:
                    return AuctionDecision(**block.input), usage
                except ValueError as exc:
                    raise AdjudicationError(str(exc), usage) from exc
        raise AdjudicationError(
            'Anthropic response did not contain submit_auction_decision', usage,
        )

    def _call_openai(self, snapshot: dict) -> tuple[AuctionDecision, dict]:
        from openai import OpenAI

        schema = AuctionDecision.model_json_schema()
        schema['additionalProperties'] = False
        model = getattr(settings, 'AUCTION_OPENAI_MODEL', 'gpt-6.1-sol')
        reasoning_effort = getattr(
            settings, 'AUCTION_OPENAI_REASONING_EFFORT', 'high',
        )
        response = OpenAI(api_key=settings.OPENAI_API_KEY).responses.create(
            model=model,
            input=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': self._message(snapshot)},
            ],
            tools=[{
                'type': 'function',
                'name': 'submit_auction_decision',
                'description': 'Submit the shadow auction-state decision.',
                'parameters': schema,
                'strict': True,
            }],
            tool_choice={'type': 'function', 'name': 'submit_auction_decision'},
            reasoning={'effort': reasoning_effort},
            max_output_tokens=4000,
        )
        # Usage is billed even when the payload is later rejected, so compute
        # it before parsing.
        usage = getattr(response, 'usage', None)
        input_tokens = getattr(usage, 'input_tokens', 0) or 0
        output_tokens = getattr(usage, 'output_tokens', 0) or 0
        input_details = getattr(usage, 'input_tokens_details', None)
        output_details = getattr(usage, 'output_tokens_details', None)
        cached_input_tokens = getattr(input_details, 'cached_tokens', 0) or 0
        reasoning_tokens = getattr(output_details, 'reasoning_tokens', 0) or 0
        usage = {
            'input_tokens': input_tokens,
            'cached_input_tokens': cached_input_tokens,
            'output_tokens': output_tokens,
            'reasoning_tokens': reasoning_tokens,
            'analysis_cost': estimate_openai_analysis_cost(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
            ),
        }
        for item in response.output:
            if item.type == 'function_call' and item.name == 'submit_auction_decision':
                try:
                    return AuctionDecision(**json.loads(item.arguments)), usage
                except ValueError as exc:
                    raise AdjudicationError(str(exc), usage) from exc
        raise AdjudicationError(
            'OpenAI response did not contain submit_auction_decision', usage,
        )

    @staticmethod
    def _validate_against_snapshot(decision: AuctionDecision, snapshot: dict) -> None:
        """Reject hallucinated authority even when schema validation succeeded."""
        registry = snapshot.get('strategy_registry') or {}
        if decision.strategy_id != 'NONE' and registry.get(decision.strategy_id) != 'SHADOW_ONLY':
            raise ValueError(f'Strategy is not in the shadow registry: {decision.strategy_id}')
        if decision.management_policy != 'NONE' and decision.management_policy not in (
            snapshot.get('allowed_management_policies') or []
        ):
            raise ValueError(f'Unknown management policy: {decision.management_policy}')
        if decision.action == 'ARM':
            if decision.direction == 'NONE' or decision.strategy_id == 'NONE':
                raise ValueError('ARM requires direction and registered strategy')
            if not decision.entry_zone or len(decision.entry_zone) != 2:
                raise ValueError('ARM requires a two-sided entry zone')
            if not decision.trigger_conditions or not decision.invalidation_conditions:
                raise ValueError('ARM requires trigger and invalidation conditions')
            if decision.management_policy == 'NONE' or decision.ttl_minutes <= 0:
                raise ValueError('ARM requires management policy and positive TTL')
            selected_low, selected_high = sorted(float(v) for v in decision.entry_zone)
            matched_zone = None
            for zone in snapshot.get('zones') or []:
                zone_low = float(zone['low'])
                zone_high = float(zone['high'])
                tolerance = max(abs(zone_low), abs(zone_high), 1.0) * 1e-8
                if (
                    abs(selected_low - zone_low) <= tolerance
                    and abs(selected_high - zone_high) <= tolerance
                ):
                    matched_zone = zone
                    break
            if matched_zone is None:
                raise ValueError('ARM entry zone must exactly match a supplied snapshot zone')
            zone_kind = matched_zone.get('kind')
            if decision.strategy_id == 'SAI1_IFVG_FLIP' and zone_kind != 'FVG':
                raise ValueError('IFVG flip requires a supplied FVG zone')
            if decision.direction == 'LONG' and zone_kind not in {'RECENT_SUPPORT', 'FVG'}:
                raise ValueError('LONG ARM requires support or FVG zone')
            if decision.direction == 'SHORT' and zone_kind not in {'RECENT_RESISTANCE', 'FVG'}:
                raise ValueError('SHORT ARM requires resistance or FVG zone')
        if snapshot.get('execution_authorized') is not False:
            raise ValueError('Auction adjudicator accepts shadow snapshots only')
