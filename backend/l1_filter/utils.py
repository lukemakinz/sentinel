"""Technical indicator helpers for L1 gate calculations."""
import math
import numpy as np


def compute_ema(data: list, period: int) -> list:
    if len(data) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(data[:period]) / period]
    for price in data[period:]:
        result.append(price * k + result[-1] * (1 - k))
    return result


def compute_atr(candles: list, period: int = 14) -> list:
    if len(candles) < 2:
        return []
    trs = [candles[0]['high'] - candles[0]['low']]
    for i in range(1, len(candles)):
        trs.append(max(
            candles[i]['high'] - candles[i]['low'],
            abs(candles[i]['high'] - candles[i - 1]['close']),
            abs(candles[i]['low']  - candles[i - 1]['close']),
        ))
    if len(trs) < period:
        avg = sum(trs) / len(trs)
        return [avg] * len(trs)
    # Wilder smoothing
    atr = [sum(trs[:period]) / period]
    for tr in trs[period:]:
        atr.append((atr[-1] * (period - 1) + tr) / period)
    return [trs[0]] * (period - 1) + atr


def compute_adx(candles: list, period: int = 14) -> float:
    """Return the most recent ADX value, or 0 if insufficient data."""
    min_candles = period * 2 + 1
    if len(candles) < min_candles:
        return 0.0

    highs  = [c['high']  for c in candles]
    lows   = [c['low']   for c in candles]
    closes = [c['close'] for c in candles]

    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        up   = highs[i]  - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up   if up > down and up > 0   else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i]  - closes[i - 1]),
            abs(lows[i]   - closes[i - 1]),
        ))

    def wilder(data):
        s = [sum(data[:period])]
        for v in data[period:]:
            s.append(s[-1] - s[-1] / period + v)
        return s

    atr_w  = wilder(trs)
    plus_w = wilder(plus_dm)
    minus_w = wilder(minus_dm)

    dx_list = []
    for i in range(len(atr_w)):
        if atr_w[i] == 0:
            dx_list.append(0.0)
            continue
        di_plus  = 100 * plus_w[i]  / atr_w[i]
        di_minus = 100 * minus_w[i] / atr_w[i]
        denom = di_plus + di_minus
        dx_list.append(100 * abs(di_plus - di_minus) / denom if denom else 0.0)

    if len(dx_list) < period:
        return 0.0

    # ADX uses average-based initialization (NOT sum-based like TR/DM smoothing)
    adx = [sum(dx_list[:period]) / period]
    for dx in dx_list[period:]:
        adx.append((adx[-1] * (period - 1) + dx) / period)

    return adx[-1] if adx else 0.0


def compute_choppiness_index(candles: list, period: int = 14) -> float:
    """
    Choppiness Index — better regime detector than ADX.
    CI < 38.2 = strong trend (trade it)
    CI 38.2-61.8 = neutral
    CI > 61.8 = choppy/ranging (avoid directional trades)
    Returns 0.0 if insufficient data.
    """
    if len(candles) < period + 1:
        return 50.0  # neutral when insufficient data

    window = candles[-period:]
    highs  = [c['high']  for c in window]
    lows   = [c['low']   for c in window]
    closes = [c['close'] for c in window]

    # Sum of individual ATRs
    trs = []
    for i in range(1, len(window)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1])
        ))

    sum_tr    = sum(trs)
    range_hl  = max(highs) - min(lows)

    if range_hl == 0 or sum_tr == 0:
        return 50.0

    ci = 100 * math.log10(sum_tr / range_hl) / math.log10(period)
    return round(ci, 2)


def is_trending(candles: list, period: int = 14) -> tuple[bool, float]:
    """
    Returns (is_trending, choppiness_index).
    Standard thresholds: CI < 38.2 = strong trend | CI 38.2-61.8 = moderate | CI > 61.8 = choppy.
    We use 61.8 as the gate threshold (industry standard, not arbitrary 50).
    """
    ci = compute_choppiness_index(candles, period)
    return ci < 61.8, ci
