"""
Cross-Asset Analyst — BTC dominance, BTC/ETH relative strength,
and macro environment scoring.
"""
import logging
from datetime import timedelta

import numpy as np
import requests
from django.utils import timezone

from .base import BaseAnalyst, AnalystSignal, Bias

logger = logging.getLogger(__name__)


class CrossAssetAnalyst(BaseAnalyst):
    """Cross-asset correlation and macro environment analysis."""

    name = 'cross_asset'

    def analyze(self, symbol: str) -> AnalystSignal:
        sub_scores = {}
        reasoning_parts = []

        # 1. BTC/ETH Relative Strength
        rs_score = self._btc_eth_relative_strength()
        sub_scores['btc_eth_rs'] = rs_score
        reasoning_parts.append(f"BTC/ETH RS: {rs_score:+.0f}")

        # 2. BTC Dominance Trend
        dom_score = self._btc_dominance_trend(symbol)
        sub_scores['btc_dominance'] = dom_score
        reasoning_parts.append(f"BTC Dom: {dom_score:+.0f}")

        # 3. Multi-pair momentum correlation
        corr_score = self._cross_pair_momentum(symbol)
        sub_scores['cross_momentum'] = corr_score
        reasoning_parts.append(f"CrossMom: {corr_score:+.0f}")

        weights = {'btc_eth_rs': 0.35, 'btc_dominance': 0.30, 'cross_momentum': 0.35}
        total = sum(sub_scores[k] * weights[k] for k in weights)
        total = float(np.clip(total, -100, 100))
        confidence = min(abs(total) / 80, 1.0)

        return AnalystSignal(
            analyst_name=self.name, symbol=symbol,
            score=total,
            bias=Bias.LONG if total > 0 else Bias.SHORT if total < 0 else Bias.NEUTRAL,
            confidence=confidence,
            reasoning=" | ".join(reasoning_parts),
            metadata={'sub_scores': {k: round(v, 2) for k, v in sub_scores.items()}},
        )

    def _btc_eth_relative_strength(self):
        """BTC vs ETH performance — risk-on/risk-off proxy."""
        from ingester.models import Candle
        now = timezone.now()

        btc = list(Candle.objects.filter(
            symbol='BTCUSDT', interval='4h', is_closed=True,
            timestamp__gte=now - timedelta(days=3),
        ).order_by('timestamp').values_list('close', flat=True))

        eth = list(Candle.objects.filter(
            symbol='ETHUSDT', interval='4h', is_closed=True,
            timestamp__gte=now - timedelta(days=3),
        ).order_by('timestamp').values_list('close', flat=True))

        if len(btc) < 5 or len(eth) < 5:
            return 0

        btc_ret = (float(btc[-1]) - float(btc[0])) / float(btc[0])
        eth_ret = (float(eth[-1]) - float(eth[0])) / float(eth[0])

        # ETH outperforming BTC = risk-on = bullish
        diff = eth_ret - btc_ret
        return float(np.clip(diff * 1000, -60, 60))

    def _btc_dominance_trend(self, symbol):
        """BTC dominance trend — falling = altcoin rotation = bullish for alts."""
        from ingester.models import MarketTicker
        now = timezone.now()

        btc_tickers = list(MarketTicker.objects.filter(
            symbol='BTCUSDT',
            timestamp__gte=now - timedelta(hours=24),
        ).order_by('timestamp').values_list('price', 'volume_24h'))

        if len(btc_tickers) < 2:
            return 0

        # Use volume as proxy for dominance trend
        vol_change = (float(btc_tickers[-1][1]) - float(btc_tickers[0][1])) / float(btc_tickers[0][1]) if float(btc_tickers[0][1]) != 0 else 0

        if symbol == 'BTCUSDT':
            return float(np.clip(vol_change * 100, -40, 40))
        else:
            # For alts, falling BTC dominance = bullish
            return float(np.clip(-vol_change * 80, -40, 40))

    def _cross_pair_momentum(self, symbol):
        """Check if majority of tracked pairs move in same direction."""
        from ingester.models import Candle
        from django.conf import settings

        now = timezone.now()
        returns = {}

        for pair in settings.TRADING_PAIRS:
            candles = list(Candle.objects.filter(
                symbol=pair, interval='1h', is_closed=True,
                timestamp__gte=now - timedelta(hours=4),
            ).order_by('timestamp').values_list('close', flat=True))

            if len(candles) >= 2:
                ret = (float(candles[-1]) - float(candles[0])) / float(candles[0])
                returns[pair] = ret

        if len(returns) < 2:
            return 0

        # Check consensus direction
        positive = sum(1 for r in returns.values() if r > 0.001)
        negative = sum(1 for r in returns.values() if r < -0.001)
        total = len(returns)

        symbol_return = returns.get(symbol, 0)

        if positive >= total * 0.75:
            return float(np.clip(symbol_return * 2000, 0, 60))
        elif negative >= total * 0.75:
            return float(np.clip(symbol_return * 2000, -60, 0))
        return 0
