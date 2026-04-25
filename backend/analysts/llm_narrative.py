"""
LLM Narrative Analyst — Agno-powered Claude agent for macro regime analysis.
"""
import json
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.db import models as db_models

from .base import BaseAnalyst, AnalystSignal, Bias

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior quantitative futures trader with 15 years of experience.
Analyze cryptocurrency futures data to identify market regime and asymmetric opportunities.
Respond with ONLY valid JSON:
{
    "regime": "accumulation|distribution|trending_up|trending_down|ranging|capitulation",
    "bias": "bullish|bearish|neutral",
    "confidence": 0.0-1.0,
    "score": -100 to 100,
    "key_observations": ["obs1", "obs2"],
    "reasoning": "Your analysis"
}"""


def _build_data_summary(symbol: str) -> str:
    from ingester.models import Candle, FundingRate, OpenInterest, LongShortRatio

    now = timezone.now()
    parts = [f"=== {symbol} Market Data ===\n"]

    candles = list(Candle.objects.filter(
        symbol=symbol, interval='1h', is_closed=True,
        timestamp__gte=now - timedelta(hours=24),
    ).order_by('-timestamp').values('open', 'high', 'low', 'close', 'volume')[:24])

    if candles:
        latest = candles[0]
        price_change = (float(latest['close']) - float(candles[-1]['close'])) / float(candles[-1]['close']) * 100
        parts.append(f"Price: ${float(latest['close']):,.2f} | 24h: {price_change:+.2f}%")
        parts.append(f"Range: ${min(float(c['low']) for c in candles):,.0f}-${max(float(c['high']) for c in candles):,.0f}")

        parts.append("\nLast 6 candles:")
        for c in candles[:6]:
            d = "🟢" if float(c['close']) > float(c['open']) else "🔴"
            parts.append(f"  {d} O:{float(c['open']):,.0f} C:{float(c['close']):,.0f} V:{float(c['volume']):,.0f}")

    funding = list(FundingRate.objects.filter(
        symbol=symbol, timestamp__gte=now - timedelta(days=3),
    ).order_by('-timestamp').values_list('funding_rate', flat=True)[:10])
    if funding:
        parts.append(f"\nFunding: {float(funding[0]):.6f} | Avg: {sum(float(f) for f in funding)/len(funding):.6f}")

    oi = list(OpenInterest.objects.filter(
        symbol=symbol, timestamp__gte=now - timedelta(hours=12),
    ).order_by('-timestamp').values_list('open_interest', flat=True)[:5])
    if oi and len(oi) > 1:
        change = (float(oi[0]) - float(oi[-1])) / float(oi[-1]) * 100
        parts.append(f"OI: {float(oi[0]):,.0f} ({change:+.2f}% 12h)")

    ls = list(LongShortRatio.objects.filter(symbol=symbol).order_by('-timestamp').values_list('long_account', 'short_account')[:1])
    if ls:
        parts.append(f"L/S: {float(ls[0][0]):.1%} / {float(ls[0][1]):.1%}")

    return "\n".join(parts)


class LLMNarrativeAnalyst(BaseAnalyst):
    name = 'llm_narrative'

    def analyze(self, symbol: str) -> AnalystSignal:
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')
        openai_key = getattr(settings, 'OPENAI_API_KEY', '')
        if not api_key and not openai_key:
            return self._neutral_signal(symbol, "LLM disabled — no API key configured")

        try:
            return self._run_analysis(symbol, api_key)
        except Exception as e:
            logger.error(f"LLM error {symbol}: {e}", exc_info=True)
            return self._neutral_signal(symbol, f"LLM error: {str(e)[:100]}")

    def _run_analysis(self, symbol: str, api_key: str) -> AnalystSignal:
        data_summary = _build_data_summary(symbol)

        openai_key = settings.OPENAI_API_KEY if hasattr(settings, 'OPENAI_API_KEY') else ''

        if api_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                msg = client.messages.create(
                    model="claude-haiku-4-5", max_tokens=1000,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": f"Analyze:\n\n{data_summary}"}]
                )
                text = msg.content[0].text
            except Exception as e:
                logger.error(f"Anthropic LLM error: {e}")
                return self._neutral_signal(symbol, f"Anthropic error: {str(e)[:80]}")
        elif openai_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=openai_key)
                resp = client.chat.completions.create(
                    model="gpt-4o-mini", max_tokens=1000,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Analyze:\n\n{data_summary}"},
                    ]
                )
                text = resp.choices[0].message.content
            except Exception as e:
                logger.error(f"OpenAI LLM error: {e}")
                return self._neutral_signal(symbol, f"OpenAI error: {str(e)[:80]}")
        else:
            return self._neutral_signal(symbol, "No LLM API key configured")

        result = self._parse_response(text)
        bias_str = result.get('bias', 'neutral').lower()
        bias = Bias.LONG if 'bull' in bias_str else Bias.SHORT if 'bear' in bias_str else Bias.NEUTRAL

        return AnalystSignal(
            analyst_name=self.name, symbol=symbol,
            score=result.get('score', 0), bias=bias,
            confidence=result.get('confidence', 0.5),
            reasoning=result.get('reasoning', text[:500]),
            metadata={'regime': result.get('regime', 'unknown'), 'key_observations': result.get('key_observations', [])},
        )

    def _parse_response(self, text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{[^{}]*"regime"[^{}]*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    logger.debug(f"LLM response JSON fallback also failed, using defaults")
        return {'regime': 'unknown', 'bias': 'neutral', 'confidence': 0.3, 'score': 0, 'reasoning': text[:500]}
