"""
Structure Analyst — Market structure analysis using SMC concepts.
Swing detection, order blocks, FVG, BOS/CHoCH, and VWAP bands.
"""
import logging
from datetime import timedelta

import numpy as np
from django.utils import timezone

from .base import BaseAnalyst, AnalystSignal, Bias

logger = logging.getLogger(__name__)


def detect_swing_points(highs, lows, lookback=5):
    """
    Zigzag swing high/low detection.
    Returns lists of (index, price, type) tuples.
    """
    swings = []
    n = len(highs)

    for i in range(lookback, n - lookback):
        # Swing High: highest high in lookback window
        if highs[i] == max(highs[i - lookback:i + lookback + 1]):
            swings.append((i, float(highs[i]), 'HH' if not swings or highs[i] > swings[-1][1] else 'LH'))

        # Swing Low: lowest low in lookback window
        if lows[i] == min(lows[i - lookback:i + lookback + 1]):
            swings.append((i, float(lows[i]), 'LL' if not swings or lows[i] < swings[-1][1] else 'HL'))

    return swings


def detect_order_blocks(opens, closes, highs, lows, volumes, lookback=30):
    """
    Detect order blocks — last opposing candle before a strong move.
    """
    blocks = []
    n = len(opens)

    for i in range(1, min(lookback, n - 1)):
        idx = n - 1 - i

        # Bullish OB: bearish candle followed by strong bullish move
        if closes[idx] < opens[idx]:  # Bearish candle
            # Check if next candles move significantly up
            if idx + 3 < n:
                move = (closes[idx + 3] - closes[idx]) / closes[idx]
                if move > 0.005:  # 0.5% move
                    blocks.append({
                        'type': 'bullish_ob',
                        'top': float(opens[idx]),
                        'bottom': float(closes[idx]),
                        'strength': float(move),
                    })

        # Bearish OB: bullish candle followed by strong bearish move
        elif closes[idx] > opens[idx]:
            if idx + 3 < n:
                move = (closes[idx] - closes[idx + 3]) / closes[idx]
                if move > 0.005:
                    blocks.append({
                        'type': 'bearish_ob',
                        'top': float(closes[idx]),
                        'bottom': float(opens[idx]),
                        'strength': float(move),
                    })

    return blocks[:5]  # Top 5 most recent


def detect_fvg(highs, lows, closes, lookback=30):
    """
    Detect Fair Value Gaps (price imbalances).
    """
    gaps = []
    n = len(highs)

    for i in range(2, min(lookback + 2, n)):
        idx = n - 1 - i

        # Bullish FVG: candle[i-2] high < candle[i] low
        if highs[idx] < lows[idx + 2]:
            gaps.append({
                'type': 'bullish_fvg',
                'top': float(lows[idx + 2]),
                'bottom': float(highs[idx]),
                'filled': float(closes[-1]) <= float(lows[idx + 2]),
            })

        # Bearish FVG: candle[i-2] low > candle[i] high
        if lows[idx] > highs[idx + 2]:
            gaps.append({
                'type': 'bearish_fvg',
                'top': float(lows[idx]),
                'bottom': float(highs[idx + 2]),
                'filled': float(closes[-1]) >= float(highs[idx + 2]),
            })

    return gaps[:5]


def detect_structure_break(swings):
    """
    Detect Break of Structure (BOS) and Change of Character (CHoCH).
    """
    if len(swings) < 4:
        return None

    recent = swings[-4:]

    # BOS: trend continuation — new HH in uptrend or new LL in downtrend
    if recent[-1][2] == 'HH' and recent[-2][2] in ('HL', 'HH'):
        return {'type': 'BOS', 'direction': 'bullish', 'level': recent[-1][1]}
    if recent[-1][2] == 'LL' and recent[-2][2] in ('LH', 'LL'):
        return {'type': 'BOS', 'direction': 'bearish', 'level': recent[-1][1]}

    # CHoCH: trend reversal — first LH after series of HHs, or first HL after LLs
    if recent[-1][2] == 'LH' and recent[-3][2] == 'HH':
        return {'type': 'CHoCH', 'direction': 'bearish', 'level': recent[-1][1]}
    if recent[-1][2] == 'HL' and recent[-3][2] == 'LL':
        return {'type': 'CHoCH', 'direction': 'bullish', 'level': recent[-1][1]}

    return None


def compute_vwap_bands(closes, volumes, highs, lows):
    """Calculate VWAP with standard deviation bands."""
    if len(closes) < 10:
        return None, None, None

    typical_prices = (np.array(closes) + np.array(highs) + np.array(lows)) / 3
    vols = np.array(volumes, dtype=float)

    cumulative_tp_vol = np.cumsum(typical_prices * vols)
    cumulative_vol = np.cumsum(vols)

    # Avoid division by zero
    mask = cumulative_vol > 0
    vwap = np.where(mask, cumulative_tp_vol / cumulative_vol, typical_prices)

    # VWAP bands (1 std dev)
    squared_diff = (typical_prices - vwap) ** 2
    cum_sq_diff = np.cumsum(squared_diff * vols)
    variance = np.where(mask, cum_sq_diff / cumulative_vol, 0)
    std_dev = np.sqrt(variance)

    return float(vwap[-1]), float(vwap[-1] + std_dev[-1]), float(vwap[-1] - std_dev[-1])


class StructureAnalyst(BaseAnalyst):
    """Market structure analysis: swings, order blocks, FVGs, BOS/CHoCH, VWAP."""

    name = 'structure'

    def analyze(self, symbol: str) -> AnalystSignal:
        from ingester.models import Candle

        candles = list(Candle.objects.filter(
            symbol=symbol, interval='1h', is_closed=True,
            timestamp__gte=timezone.now() - timedelta(days=5),
        ).order_by('timestamp').values('open', 'high', 'low', 'close', 'volume'))

        if len(candles) < 30:
            return self._neutral_signal(symbol, f"Insufficient structure data ({len(candles)} candles)")

        opens = [float(c['open']) for c in candles]
        highs = [float(c['high']) for c in candles]
        lows = [float(c['low']) for c in candles]
        closes = [float(c['close']) for c in candles]
        volumes = [float(c['volume']) for c in candles]

        current_price = closes[-1]
        reasoning_parts = []
        score = 0

        # 1. Swing points
        swings = detect_swing_points(
            np.array(highs), np.array(lows), lookback=5
        )

        # 2. Structure break detection
        structure = detect_structure_break(swings)
        if structure:
            if structure['type'] == 'BOS':
                adj = 30 if structure['direction'] == 'bullish' else -30
            else:  # CHoCH
                adj = 40 if structure['direction'] == 'bullish' else -40
            score += adj
            reasoning_parts.append(f"{structure['type']} {structure['direction']} @ {structure['level']:.2f} ({adj:+d})")

        # 3. Order blocks
        obs = detect_order_blocks(
            np.array(opens), np.array(closes),
            np.array(highs), np.array(lows),
            np.array(volumes)
        )
        bullish_obs = [ob for ob in obs if ob['type'] == 'bullish_ob']
        bearish_obs = [ob for ob in obs if ob['type'] == 'bearish_ob']

        # Is price near an order block?
        for ob in bullish_obs:
            if ob['bottom'] <= current_price <= ob['top'] * 1.005:
                score += 20
                reasoning_parts.append(f"Price at bullish OB [{ob['bottom']:.0f}-{ob['top']:.0f}]")
                break

        for ob in bearish_obs:
            if ob['bottom'] * 0.995 <= current_price <= ob['top']:
                score -= 20
                reasoning_parts.append(f"Price at bearish OB [{ob['bottom']:.0f}-{ob['top']:.0f}]")
                break

        # 4. Fair Value Gaps
        fvgs = detect_fvg(
            np.array(highs), np.array(lows), np.array(closes)
        )
        unfilled_bullish = [g for g in fvgs if g['type'] == 'bullish_fvg' and not g['filled']]
        unfilled_bearish = [g for g in fvgs if g['type'] == 'bearish_fvg' and not g['filled']]

        if unfilled_bullish:
            score += 10
            reasoning_parts.append(f"{len(unfilled_bullish)} unfilled bullish FVGs below")
        if unfilled_bearish:
            score -= 10
            reasoning_parts.append(f"{len(unfilled_bearish)} unfilled bearish FVGs above")

        # 5. VWAP analysis
        vwap, upper_band, lower_band = compute_vwap_bands(closes, volumes, highs, lows)
        if vwap:
            if current_price > upper_band:
                score -= 15
                reasoning_parts.append(f"Price above VWAP upper band ({upper_band:.0f})")
            elif current_price < lower_band:
                score += 15
                reasoning_parts.append(f"Price below VWAP lower band ({lower_band:.0f})")
            else:
                reasoning_parts.append(f"Price within VWAP bands ({lower_band:.0f}-{upper_band:.0f})")

        score = float(np.clip(score, -100, 100))
        confidence = min(abs(score) / 70, 1.0)

        # Key levels for metadata
        key_levels = {
            'vwap': vwap,
            'vwap_upper': upper_band,
            'vwap_lower': lower_band,
            'swing_highs': [s[1] for s in swings if 'H' in s[2]][-3:],
            'swing_lows': [s[1] for s in swings if 'L' in s[2]][-3:],
            'order_blocks': obs[:3],
        }

        return AnalystSignal(
            analyst_name=self.name,
            symbol=symbol,
            score=score,
            bias=Bias.LONG if score > 0 else Bias.SHORT if score < 0 else Bias.NEUTRAL,
            confidence=confidence,
            reasoning=" | ".join(reasoning_parts) if reasoning_parts else "Neutral structure",
            metadata={'key_levels': key_levels},
        )
