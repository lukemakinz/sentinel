from .base import BaseAgent

SYSTEM_PROMPT = """You are a quantitative order flow analyst for cryptocurrency futures.
Your role: evaluate Whale vs Retail Cumulative Volume Delta (CVD), Open Interest, and absorption signals.

Do NOT generate entry prices, stop-loss, or take-profit levels. That is forbidden.

Analyze:
- Whale CVD trend: are large players (>$10k trades) accumulating or distributing?
- Retail CVD trend: are small players positioned against or with the trade?
- Open Interest direction: rising OI with price = trend conviction; falling OI = covering
- Absorption: are large players absorbing retail selling (bullish) or retail buying (bearish)?
- Funding rate as sentiment proxy

Output valid JSON. verdict must be APPROVE, REJECT, or NEUTRAL.
confidence is 0-100. reasoning is a concise explanation (max 3 sentences).
"""


class OrderFlowQuantAgent(BaseAgent):
    """Agent 2: Quantitative order flow and CVD analyst."""
    system_prompt = SYSTEM_PROMPT

    def _build_user_message(self, ctx: dict) -> str:
        from ingester.models import WhaleCVD, RetailCVD
        from django.utils import timezone
        from datetime import timedelta

        symbol = ctx.get('symbol', '')
        direction = ctx.get('direction', '')

        # Enrich with live CVD data if available
        cvd_info = ''
        try:
            cutoff = timezone.now() - timedelta(hours=4)
            whale_cvd = list(
                WhaleCVD.objects.filter(symbol=symbol, timestamp__gte=cutoff)
                .order_by('timestamp').values_list('cumulative_delta', flat=True)
            )
            retail_cvd = list(
                RetailCVD.objects.filter(symbol=symbol, timestamp__gte=cutoff)
                .order_by('timestamp').values_list('cumulative_delta', flat=True)
            )
            if whale_cvd and retail_cvd:
                whale_trend = 'rising' if whale_cvd[-1] > whale_cvd[0] else 'falling'
                retail_trend = 'rising' if retail_cvd[-1] > retail_cvd[0] else 'falling'
                cvd_info = (
                    f"\nWhaleCVD (4h): {float(whale_cvd[0]):.0f} → {float(whale_cvd[-1]):.0f} ({whale_trend})"
                    f"\nRetailCVD (4h): {float(retail_cvd[0]):.0f} → {float(retail_cvd[-1]):.0f} ({retail_trend})"
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"CVD fetch skipped for {symbol}: {e}")

        return (
            f"Analyze this {direction} setup on {symbol}.\n\n"
            f"TradeContext:\n{self._format_context(ctx)}"
            f"{cvd_info}\n\n"
            f"Return your verdict as structured JSON."
        )
