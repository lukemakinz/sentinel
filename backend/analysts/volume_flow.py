"""
Volume/Flow Analyst — CVD, OBV Rate of Change, Funding rate trends,
OI divergence, and liquidation cascade detection.
"""
import logging
from datetime import timedelta

import numpy as np
from django.utils import timezone

from .base import BaseAnalyst, AnalystSignal, Bias

logger = logging.getLogger(__name__)


class VolumeFlowAnalyst(BaseAnalyst):
    """Analyzes volume flows, funding, OI, and liquidation patterns."""

    name = 'volume_flow'

    def analyze(self, symbol: str) -> AnalystSignal:
        from ingester.models import Candle, FundingRate, OpenInterest, Liquidation

        now = timezone.now()
        sub_scores = {}
        reasoning_parts = []

        # --- 1. Cumulative Volume Delta (CVD) ---
        cvd_score = self._analyze_cvd(symbol, now)
        sub_scores['cvd'] = cvd_score
        reasoning_parts.append(f"CVD: {cvd_score:+.0f}")

        # --- 2. OBV Rate of Change ---
        obv_score = self._analyze_obv_roc(symbol, now)
        sub_scores['obv_roc'] = obv_score
        reasoning_parts.append(f"OBV RoC: {obv_score:+.0f}")

        # --- 3. Funding Rate Trend ---
        funding_score = self._analyze_funding(symbol, now)
        sub_scores['funding'] = funding_score
        reasoning_parts.append(f"Funding: {funding_score:+.0f}")

        # --- 4. OI vs Price Divergence ---
        oi_score = self._analyze_oi_divergence(symbol, now)
        sub_scores['oi_divergence'] = oi_score
        reasoning_parts.append(f"OI div: {oi_score:+.0f}")

        # --- 5. Liquidation Cascade Detection ---
        liq_score = self._analyze_liquidations(symbol, now)
        sub_scores['liquidations'] = liq_score
        reasoning_parts.append(f"Liqs: {liq_score:+.0f}")

        # Weighted combination
        weights = {
            'cvd': 0.25,
            'obv_roc': 0.20,
            'funding': 0.20,
            'oi_divergence': 0.20,
            'liquidations': 0.15,
        }
        total_score = sum(sub_scores[k] * weights[k] for k in weights)
        total_score = np.clip(total_score, -100, 100)

        confidence = min(abs(total_score) / 80, 1.0)

        return AnalystSignal(
            analyst_name=self.name,
            symbol=symbol,
            score=float(total_score),
            bias=Bias.LONG if total_score > 0 else Bias.SHORT if total_score < 0 else Bias.NEUTRAL,
            confidence=confidence,
            reasoning=" | ".join(reasoning_parts),
            metadata={'sub_scores': {k: round(v, 2) for k, v in sub_scores.items()}},
        )

    def _analyze_cvd(self, symbol, now):
        """CVD: taker buy volume - taker sell volume accumulation."""
        from ingester.models import Candle

        candles = Candle.objects.filter(
            symbol=symbol, interval='5m', is_closed=True,
            timestamp__gte=now - timedelta(hours=4),
        ).order_by('timestamp').values('volume', 'taker_buy_volume')

        candles = list(candles)
        if len(candles) < 10:
            return 0

        cvd = []
        cumulative = 0
        for c in candles:
            buy_vol = float(c['taker_buy_volume'])
            total_vol = float(c['volume'])
            sell_vol = total_vol - buy_vol
            delta = buy_vol - sell_vol
            cumulative += delta
            cvd.append(cumulative)

        if len(cvd) < 5:
            return 0

        # Check trend: is CVD rising or falling?
        recent_cvd = cvd[-10:]
        slope = np.polyfit(range(len(recent_cvd)), recent_cvd, 1)[0]

        # Normalize to -100..+100 based on total volume
        total_volume = sum(float(c['volume']) for c in candles)
        if total_volume == 0:
            return 0
        normalized = (slope * len(candles)) / (total_volume / len(candles)) * 200
        return float(np.clip(normalized, -100, 100))

    def _analyze_obv_roc(self, symbol, now):
        """OBV Rate of Change — acceleration of on-balance volume."""
        from ingester.models import Candle

        candles = Candle.objects.filter(
            symbol=symbol, interval='15m', is_closed=True,
            timestamp__gte=now - timedelta(hours=12),
        ).order_by('timestamp').values('close', 'volume')

        candles = list(candles)
        if len(candles) < 20:
            return 0

        # Calculate OBV
        obv = [0]
        for i in range(1, len(candles)):
            curr_close = float(candles[i]['close'])
            prev_close = float(candles[i - 1]['close'])
            vol = float(candles[i]['volume'])

            if curr_close > prev_close:
                obv.append(obv[-1] + vol)
            elif curr_close < prev_close:
                obv.append(obv[-1] - vol)
            else:
                obv.append(obv[-1])

        # Rate of change of OBV (10-period)
        roc_period = min(10, len(obv) - 1)
        if obv[-roc_period - 1] == 0:
            return 0

        obv_roc = (obv[-1] - obv[-roc_period - 1]) / abs(obv[-roc_period - 1]) * 100

        return float(np.clip(obv_roc, -100, 100))

    def _analyze_funding(self, symbol, now):
        """Funding rate trend — extreme funding = contrarian signal."""
        from ingester.models import FundingRate

        rates = FundingRate.objects.filter(
            symbol=symbol,
            timestamp__gte=now - timedelta(days=3),
        ).order_by('timestamp').values_list('funding_rate', flat=True)

        rates = [float(r) for r in rates]
        if len(rates) < 3:
            return 0

        current_rate = rates[-1]
        avg_rate = np.mean(rates)

        # Extreme positive funding = bearish contrarian (too many longs)
        # Extreme negative funding = bullish contrarian (too many shorts)
        if abs(current_rate) > 0.001:  # 0.1%
            score = -current_rate * 50000  # Scale: 0.001 → ±50
        else:
            score = -current_rate * 20000  # Moderate scaling

        return float(np.clip(score, -100, 100))

    def _analyze_oi_divergence(self, symbol, now):
        """OI vs Price divergence — rising OI + falling price = bearish setup."""
        from ingester.models import OpenInterest, Candle

        oi_data = OpenInterest.objects.filter(
            symbol=symbol,
            timestamp__gte=now - timedelta(hours=6),
        ).order_by('timestamp').values_list('open_interest', flat=True)

        prices = Candle.objects.filter(
            symbol=symbol, interval='1h', is_closed=True,
            timestamp__gte=now - timedelta(hours=6),
        ).order_by('timestamp').values_list('close', flat=True)

        oi_list = [float(o) for o in oi_data]
        price_list = [float(p) for p in prices]

        if len(oi_list) < 3 or len(price_list) < 3:
            return 0

        # Normalize changes
        oi_change = (oi_list[-1] - oi_list[0]) / oi_list[0] if oi_list[0] != 0 else 0
        price_change = (price_list[-1] - price_list[0]) / price_list[0] if price_list[0] != 0 else 0

        # Divergence scoring
        if oi_change > 0.02 and price_change < -0.005:
            # Rising OI + falling price = shorts building
            return -60
        elif oi_change > 0.02 and price_change > 0.005:
            # Rising OI + rising price = longs building
            return 60
        elif oi_change < -0.02:
            # Falling OI = positions closing, neutral
            return 0
        else:
            return float(np.clip(price_change * 1000, -30, 30))

    def _analyze_liquidations(self, symbol, now):
        """Detect liquidation cascades — large liq volume = potential reversal."""
        from ingester.models import Liquidation

        recent_liqs = Liquidation.objects.filter(
            symbol=symbol,
            timestamp__gte=now - timedelta(hours=1),
        ).values('side', 'usd_value')

        liqs = list(recent_liqs)
        if not liqs:
            return 0

        buy_liq_value = sum(float(l['usd_value']) for l in liqs if l['side'] == 'BUY')
        sell_liq_value = sum(float(l['usd_value']) for l in liqs if l['side'] == 'SELL')

        total = buy_liq_value + sell_liq_value
        if total < 100000:  # Below $100k = not significant
            return 0

        # Heavy sell liquidations = shorts getting rekt = bullish
        # Heavy buy liquidations = longs getting rekt = bearish
        if sell_liq_value > buy_liq_value * 2:
            return min(80, sell_liq_value / 1000000 * 100)  # Scale by $1M
        elif buy_liq_value > sell_liq_value * 2:
            return max(-80, -buy_liq_value / 1000000 * 100)
        else:
            return 0
