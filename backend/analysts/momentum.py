"""
Momentum Analyst — Multi-timeframe RSI/MACD scoring with divergence detection.
Compares momentum indicators across 5m, 15m, 1h, 4h simultaneously.
"""
import logging
from datetime import timedelta

import numpy as np
from django.utils import timezone

from .base import BaseAnalyst, AnalystSignal, Bias

logger = logging.getLogger(__name__)

# Timeframes to analyze with relative importance weights
TIMEFRAMES = {
    '5m': {'weight': 0.10, 'candle_count': 100},
    '15m': {'weight': 0.20, 'candle_count': 100},
    '1h': {'weight': 0.30, 'candle_count': 100},
    '4h': {'weight': 0.40, 'candle_count': 100},
}


def compute_rsi(closes, period=14):
    """Calculate RSI from closing prices."""
    if len(closes) < period + 1:
        return np.array([50.0])

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    rsi_values = []
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

    return np.array(rsi_values) if rsi_values else np.array([50.0])


def compute_macd(closes, fast=12, slow=26, signal=9):
    """Calculate MACD, signal line, and histogram."""
    if len(closes) < slow + signal:
        return 0, 0, 0

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = ema_fast - ema_slow

    if len(macd_line) < signal:
        return macd_line[-1], 0, macd_line[-1]

    signal_line = _ema(macd_line, signal)
    histogram = macd_line[-1] - signal_line[-1]

    return macd_line[-1], signal_line[-1], histogram


def _ema(data, period):
    """Exponential Moving Average."""
    if len(data) < period:
        return data
    multiplier = 2 / (period + 1)
    ema = [np.mean(data[:period])]
    for price in data[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return np.array(ema)


def detect_divergence(prices, indicators, lookback=20):
    """
    Detect bullish/bearish divergence between price and indicator.
    Returns: 'bullish', 'bearish', or None
    """
    if len(prices) < lookback or len(indicators) < lookback:
        return None

    recent_prices = prices[-lookback:]
    recent_ind = indicators[-lookback:]

    # Find local lows and highs
    price_low_idx = np.argmin(recent_prices)
    price_high_idx = np.argmax(recent_prices)

    # Bullish divergence: price makes lower low, indicator makes higher low
    if price_low_idx > lookback // 2:  # Recent low
        prev_price_low = np.min(recent_prices[:lookback // 2])
        if recent_prices[price_low_idx] < prev_price_low:
            prev_ind_low = np.min(recent_ind[:lookback // 2])
            curr_ind_low = recent_ind[price_low_idx]
            if curr_ind_low > prev_ind_low:
                return 'bullish'

    # Bearish divergence: price makes higher high, indicator makes lower high
    if price_high_idx > lookback // 2:
        prev_price_high = np.max(recent_prices[:lookback // 2])
        if recent_prices[price_high_idx] > prev_price_high:
            prev_ind_high = np.max(recent_ind[:lookback // 2])
            curr_ind_high = recent_ind[price_high_idx]
            if curr_ind_high < prev_ind_high:
                return 'bearish'

    return None


def detect_divergence_extended(prices, indicators, lookback=20):
    """
    Detect regular and hidden divergence.
    Returns one of:
    - bullish
    - bearish
    - bullish_hidden
    - bearish_hidden
    - None
    """
    if len(prices) < lookback or len(indicators) < lookback:
        return None

    recent_prices = prices[-lookback:]
    recent_ind = indicators[-lookback:]
    half = lookback // 2

    prev_prices = recent_prices[:half]
    curr_prices = recent_prices[half:]
    prev_ind = recent_ind[:half]
    curr_ind = recent_ind[half:]

    prev_low_idx = int(np.argmin(prev_prices))
    curr_low_idx = int(np.argmin(curr_prices))
    prev_high_idx = int(np.argmax(prev_prices))
    curr_high_idx = int(np.argmax(curr_prices))

    prev_price_low = float(prev_prices[prev_low_idx])
    curr_price_low = float(curr_prices[curr_low_idx])
    prev_ind_low = float(prev_ind[min(prev_low_idx, len(prev_ind) - 1)])
    curr_ind_low = float(curr_ind[min(curr_low_idx, len(curr_ind) - 1)])

    prev_price_high = float(prev_prices[prev_high_idx])
    curr_price_high = float(curr_prices[curr_high_idx])
    prev_ind_high = float(prev_ind[min(prev_high_idx, len(prev_ind) - 1)])
    curr_ind_high = float(curr_ind[min(curr_high_idx, len(curr_ind) - 1)])

    if curr_price_low < prev_price_low and curr_ind_low > prev_ind_low:
        return 'bullish'
    if curr_price_high > prev_price_high and curr_ind_high < prev_ind_high:
        return 'bearish'
    if curr_price_low > prev_price_low and curr_ind_low < prev_ind_low:
        return 'bullish_hidden'
    if curr_price_high < prev_price_high and curr_ind_high > prev_ind_high:
        return 'bearish_hidden'

    return None


class MomentumAnalyst(BaseAnalyst):
    """Multi-timeframe momentum scoring using RSI and MACD alignment."""

    name = 'momentum'

    def analyze(self, symbol: str) -> AnalystSignal:
        from ingester.models import Candle

        tf_scores = {}
        divergences = []
        reasoning_parts = []

        for tf, config in TIMEFRAMES.items():
            candles = Candle.objects.filter(
                symbol=symbol,
                interval=tf,
                is_closed=True,
            ).order_by('timestamp').values_list('close', flat=True)[:config['candle_count']]

            closes = np.array([float(c) for c in candles])

            if len(closes) < 30:
                tf_scores[tf] = 0
                reasoning_parts.append(f"{tf}: insufficient data ({len(closes)} candles)")
                continue

            # RSI scoring
            rsi_values = compute_rsi(closes)
            current_rsi = rsi_values[-1] if len(rsi_values) > 0 else 50

            # Map RSI to score: 50=neutral, >70=overbought(bearish), <30=oversold(bullish)
            if current_rsi > 70:
                rsi_score = -((current_rsi - 70) / 30) * 100  # -100 at RSI=100
            elif current_rsi < 30:
                rsi_score = ((30 - current_rsi) / 30) * 100  # +100 at RSI=0
            else:
                rsi_score = (50 - current_rsi) / 20 * 50  # Moderate score in middle zone

            # MACD scoring
            macd_val, signal_val, hist = compute_macd(closes)
            price_range = closes[-1] if closes[-1] != 0 else 1
            normalized_hist = (hist / price_range) * 10000  # Normalize
            macd_score = np.clip(normalized_hist, -100, 100)

            # Combined TF score
            tf_score = (rsi_score * 0.5 + macd_score * 0.5)
            tf_scores[tf] = tf_score

            reasoning_parts.append(
                f"{tf}: RSI={current_rsi:.1f}({rsi_score:+.0f}) MACD_H={hist:.4f}({macd_score:+.0f}) → {tf_score:+.0f}"
            )

            # Divergence detection
            div = detect_divergence(closes, rsi_values)
            if div:
                divergences.append(f"{tf}:{div}")

        if not tf_scores:
            return self._neutral_signal(symbol, "No timeframe data available")

        # Weighted score
        total_score = sum(
            tf_scores.get(tf, 0) * config['weight']
            for tf, config in TIMEFRAMES.items()
        )

        # Alignment bonus: if all TFs agree on direction, boost score by 20%
        directions = [1 if s > 10 else (-1 if s < -10 else 0) for s in tf_scores.values()]
        non_neutral = [d for d in directions if d != 0]
        if len(non_neutral) >= 3 and len(set(non_neutral)) == 1:
            alignment = "ALIGNED"
            total_score *= 1.2
            reasoning_parts.append(f"⚡ TF alignment bonus (all {non_neutral[0]:+d})")
        else:
            alignment = "MIXED"

        # Divergence adjustments
        for div in divergences:
            if 'bullish' in div:
                total_score += 15
            elif 'bearish' in div:
                total_score -= 15
            reasoning_parts.append(f"📊 Divergence: {div}")

        total_score = np.clip(total_score, -100, 100)

        confidence = min(abs(total_score) / 100, 1.0)

        return AnalystSignal(
            analyst_name=self.name,
            symbol=symbol,
            score=float(total_score),
            bias=Bias.LONG if total_score > 0 else Bias.SHORT if total_score < 0 else Bias.NEUTRAL,
            confidence=confidence,
            reasoning=f"Momentum {alignment} | " + " | ".join(reasoning_parts),
            metadata={
                'tf_scores': {k: round(v, 2) for k, v in tf_scores.items()},
                'divergences': divergences,
                'alignment': alignment,
            }
        )
