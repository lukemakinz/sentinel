"""Gate A: Bias & Context — all 5 must pass."""
from datetime import datetime, timezone

from .utils import compute_ema, compute_adx, is_trending

LONDON_START, LONDON_END = 7, 10   # UTC hours [start, end)
NY_START,     NY_END     = 13, 16
FUNDING_THRESHOLD        = 0.001   # 0.1%
ADX_THRESHOLD            = 20
HTF_MIN_CANDLES          = 51      # need at least 50 for EMA50


def check_killzone(now: datetime) -> tuple[bool, dict]:
    hour = now.hour
    if LONDON_START <= hour < LONDON_END:
        return True, {'session': 'london'}
    if NY_START <= hour < NY_END:
        return True, {'session': 'ny'}
    return False, {'session': None}


def check_htf_trend(candles: list) -> tuple[bool, dict]:
    """
    A2: HTF Bias from market STRUCTURE (HH/HL vs LH/LL), not EMA crossover.
    EMA is a lagging indicator — structure is real-time.
    Requires minimum 3 swings to confirm a trend.
    Falls back to EMA if insufficient swing data.
    """
    import numpy as np
    if len(candles) < HTF_MIN_CANDLES:
        return False, {'reason': 'insufficient_data'}

    highs  = np.array([c['high']  for c in candles])
    lows   = np.array([c['low']   for c in candles])
    closes = [c['close'] for c in candles]
    last_close = closes[-1]

    # Use structure detection (min 3 swings for trend confirmation)
    from analysts.structure import detect_swing_points
    lookback = max(3, len(candles) // 15)
    swings = detect_swing_points(highs, lows, lookback=lookback)

    if len(swings) >= 3:
        # Classify last 4 swings
        recent = swings[-4:] if len(swings) >= 4 else swings
        swing_highs = [(i, p) for i, p, t in recent if 'H' in t]
        swing_lows  = [(i, p) for i, p, t in recent if 'L' in t]

        if len(swing_highs) >= 3 and len(swing_lows) >= 3:
            # Require 2 consecutive HH AND 2 consecutive HL for bullish (3 points each)
            hh2 = (swing_highs[-1][1] > swing_highs[-2][1] and
                   swing_highs[-2][1] > swing_highs[-3][1])
            hl2 = (swing_lows[-1][1]  > swing_lows[-2][1]  and
                   swing_lows[-2][1]  > swing_lows[-3][1])

            lh2 = (swing_highs[-1][1] < swing_highs[-2][1] and
                   swing_highs[-2][1] < swing_highs[-3][1])
            ll2 = (swing_lows[-1][1]  < swing_lows[-2][1]  and
                   swing_lows[-2][1]  < swing_lows[-3][1])

            hh = swing_highs[-1][1] > swing_highs[-2][1]
            hl = swing_lows[-1][1]  > swing_lows[-2][1]
            lh = swing_highs[-1][1] < swing_highs[-2][1]
            ll = swing_lows[-1][1]  < swing_lows[-2][1]

            # Minimum 1 consecutive pair: single HH + single HL sufficient for bias
            if hh and hl:
                return True, {
                    'direction': 'LONG',
                    'basis': 'structure_HH_HL',
                    'last_hh': round(swing_highs[-1][1], 4),
                    'last_hl': round(swing_lows[-1][1], 4),
                }
            if lh and ll:
                return True, {
                    'direction': 'SHORT',
                    'basis': 'structure_LH_LL',
                    'last_lh': round(swing_highs[-1][1], 4),
                    'last_ll': round(swing_lows[-1][1], 4),
                }

    # Fallback: EMA-based bias (less precise, acceptable for small candle sets)
    ema50_series = compute_ema(closes, 50)
    ema50 = ema50_series[-1] if ema50_series else None
    if ema50 is None:
        return False, {'reason': 'insufficient_swing_data'}

    EMA_MARGIN = 0.005
    if len(closes) >= 100:
        proxy_series = compute_ema(closes, min(200, len(closes)))
        ema200 = proxy_series[-1] if proxy_series else None
        if ema200:
            if ema50 > ema200 * (1 + EMA_MARGIN) and last_close > ema50:
                return True, {'direction': 'LONG', 'basis': 'ema_fallback', 'ema50': ema50}
            if ema50 < ema200 * (1 - EMA_MARGIN) and last_close < ema50:
                return True, {'direction': 'SHORT', 'basis': 'ema_fallback', 'ema50': ema50}

    return False, {'reason': 'no_clear_structural_trend'}


def check_btc_correlation(btc_candles: list, direction: str, symbol: str) -> tuple[bool, dict]:
    if symbol == 'BTCUSDT':
        return True, {'btc_trend': 'self'}

    if len(btc_candles) < 22:
        return True, {'btc_trend': 'unknown'}  # pass on insufficient data

    closes = [c['close'] for c in btc_candles]
    ema9  = compute_ema(closes, 9)
    ema21 = compute_ema(closes, 21)

    if not ema9 or not ema21:
        return True, {'btc_trend': 'unknown'}

    btc_bullish = ema9[-1] > ema21[-1]
    btc_trend = 'bullish' if btc_bullish else 'bearish'

    if direction == 'LONG'  and not btc_bullish:
        return False, {'btc_trend': btc_trend}
    if direction == 'SHORT' and btc_bullish:
        return False, {'btc_trend': btc_trend}

    return True, {'btc_trend': btc_trend}


def check_funding_rate(funding_rate: float, direction: str) -> tuple[bool, dict]:
    passed = abs(funding_rate) < FUNDING_THRESHOLD
    return passed, {'funding_rate': funding_rate}


def check_adx(candles: list) -> tuple[bool, dict]:
    """
    A5 Regime filter — now uses Choppiness Index (CI) instead of ADX.
    CI < 50 = trending (pass) | CI > 50 = choppy (fail)
    ADX kept as secondary metric for display.
    """
    if len(candles) < 15:
        return False, {'adx_value': 0.0, 'reason': 'insufficient_data'}

    trending, ci = is_trending(candles)

    atr_series = [c['high'] - c['low'] for c in candles]
    avg_atr = sum(atr_series[-14:]) / 14 if len(atr_series) >= 14 else 0.0

    # Keep ADX for display / legacy tests
    adx_value = compute_adx(candles) if len(candles) >= 29 else 0.0

    return trending, {
        'adx_value': round(adx_value, 2),
        'choppiness_index': ci,
        'regime': 'trending' if trending else 'choppy',
        'atr': round(avg_atr, 4),
    }
