"""
Sentiment Analyst — Long/Short ratio, top trader positions,
Fear & Greed index, and contrarian signals.
"""
import logging
from datetime import timedelta

import numpy as np
import requests
from django.utils import timezone

from .base import BaseAnalyst, AnalystSignal, Bias

logger = logging.getLogger(__name__)

FEAR_GREED_API = 'https://api.alternative.me/fng/'


class SentimentAnalyst(BaseAnalyst):
    """Crowd sentiment + contrarian signal detection."""

    name = 'sentiment'

    def analyze(self, symbol: str) -> AnalystSignal:
        sub_scores = {}
        reasoning_parts = []

        # 1. Long/Short Ratio
        ls_score = self._analyze_long_short_ratio(symbol)
        sub_scores['long_short'] = ls_score
        reasoning_parts.append(f"L/S: {ls_score:+.0f}")

        # 2. Top Trader Positions
        tt_score = self._analyze_top_traders(symbol)
        sub_scores['top_traders'] = tt_score
        reasoning_parts.append(f"TopTraders: {tt_score:+.0f}")

        # 3. Fear & Greed Index
        fg_score = self._analyze_fear_greed()
        sub_scores['fear_greed'] = fg_score
        reasoning_parts.append(f"F&G: {fg_score:+.0f}")

        # 4. Funding as Sentiment
        funding_score = self._analyze_funding_sentiment(symbol)
        sub_scores['funding'] = funding_score
        reasoning_parts.append(f"FundSent: {funding_score:+.0f}")

        # Weighted combination
        weights = {
            'long_short': 0.30,
            'top_traders': 0.25,
            'fear_greed': 0.25,
            'funding': 0.20,
        }
        total_score = sum(sub_scores[k] * weights[k] for k in weights)
        total_score = float(np.clip(total_score, -100, 100))

        # Contrarian alert
        contrarian = False
        if abs(total_score) > 60:
            contrarian = True
            reasoning_parts.append("⚠️ CONTRARIAN ALERT — extreme sentiment")

        confidence = min(abs(total_score) / 80, 1.0)

        return AnalystSignal(
            analyst_name=self.name,
            symbol=symbol,
            score=total_score,
            bias=Bias.LONG if total_score > 0 else Bias.SHORT if total_score < 0 else Bias.NEUTRAL,
            confidence=confidence,
            reasoning=" | ".join(reasoning_parts),
            metadata={
                'sub_scores': {k: round(v, 2) for k, v in sub_scores.items()},
                'contrarian_alert': contrarian,
            },
        )

    def _analyze_long_short_ratio(self, symbol):
        """Contrarian: extreme L/S ratio = fade the crowd."""
        from ingester.models import LongShortRatio

        ratios = LongShortRatio.objects.filter(
            symbol=symbol,
        ).order_by('-timestamp').values_list('long_short_ratio', 'long_account', 'short_account')[:10]

        ratios = list(ratios)
        if not ratios:
            return 0

        current_ratio = float(ratios[0][0])
        long_pct = float(ratios[0][1])
        short_pct = float(ratios[0][2])

        # Extreme long (>70%) = bearish contrarian
        # Extreme short (>70%) = bullish contrarian
        if long_pct > 0.70:
            return -(long_pct - 0.50) * 300  # Max ~-90
        elif short_pct > 0.70:
            return (short_pct - 0.50) * 300  # Max ~+90
        elif long_pct > 0.60:
            return -(long_pct - 0.50) * 150
        elif short_pct > 0.60:
            return (short_pct - 0.50) * 150
        else:
            return 0

    def _analyze_top_traders(self, symbol):
        """Top trader positions — smart money indicator."""
        from ingester.models import TopTraderPosition

        positions = TopTraderPosition.objects.filter(
            symbol=symbol,
        ).order_by('-timestamp').values_list('long_account', 'short_account')[:5]

        positions = list(positions)
        if not positions:
            return 0

        long_pct = float(positions[0][0])
        short_pct = float(positions[0][1])

        # Follow the smart money (not contrarian)
        if long_pct > 0.60:
            return (long_pct - 0.50) * 200
        elif short_pct > 0.60:
            return -(short_pct - 0.50) * 200
        else:
            return 0

    def _analyze_fear_greed(self):
        """Crypto Fear & Greed Index — contrarian at extremes."""
        try:
            response = requests.get(FEAR_GREED_API, timeout=5)
            data = response.json()
            value = int(data['data'][0]['value'])

            # 0-25 = Extreme Fear (bullish contrarian)
            # 75-100 = Extreme Greed (bearish contrarian)
            if value < 20:
                return 80
            elif value < 30:
                return 50
            elif value < 40:
                return 20
            elif value > 80:
                return -80
            elif value > 70:
                return -50
            elif value > 60:
                return -20
            else:
                return 0

        except Exception as e:
            logger.warning(f"Fear & Greed API error: {e}")
            return 0

    def _analyze_funding_sentiment(self, symbol):
        """Funding rate as crowd positioning proxy."""
        from ingester.models import FundingRate

        rates = FundingRate.objects.filter(
            symbol=symbol,
        ).order_by('-timestamp').values_list('funding_rate', flat=True)[:10]

        rates = [float(r) for r in rates]
        if not rates:
            return 0

        current = rates[0]
        avg = np.mean(rates)

        # Contrarian: extreme funding = fade
        if current > 0.0005:  # 0.05%+ positive = too many longs
            return -min(abs(current) * 100000, 80)
        elif current < -0.0005:  # 0.05%+ negative = too many shorts
            return min(abs(current) * 100000, 80)
        else:
            return 0
