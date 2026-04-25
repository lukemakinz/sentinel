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
    if len(candles) < HTF_MIN_CANDLES:
        return False, {'reason': 'insufficient_data'}

    closes = [c['close'] for c in candles]
    ema50_series  = compute_ema(closes, 50)
    ema50  = ema50_series[-1]  if ema50_series  else None

    # EMA200 only if enough data; otherwise use EMA100 as proxy
    if len(closes) >= 200:
        ema200_series = compute_ema(closes, 200)
        ema200 = ema200_series[-1]
    elif len(closes) >= 100:
        ema200_series = compute_ema(closes, 100)
        ema200 = ema200_series[-1]
    else:
        ema200 = None

    last_close = closes[-1]

    if ema50 is None:
        return False, {'reason': 'ema50_unavailable'}

    EMA_MARGIN = 0.005  # EMA50 must differ from EMA200 by at least 0.5%

    if ema200 is not None:
        if ema50 > ema200 * (1 + EMA_MARGIN) and last_close > ema50:
            return True, {'direction': 'LONG', 'ema50': ema50, 'ema200': ema200}
        if ema50 < ema200 * (1 - EMA_MARGIN) and last_close < ema50:
            return True, {'direction': 'SHORT', 'ema50': ema50, 'ema200': ema200}
    else:
        # Only EMA50 available — use slope heuristic (require 1% slope)
        mid = ema50_series[len(ema50_series) // 2]
        if ema50 > mid * 1.01 and last_close > ema50:
            return True, {'direction': 'LONG', 'ema50': ema50, 'ema200': None}
        if ema50 < mid * 0.99 and last_close < ema50:
            return True, {'direction': 'SHORT', 'ema50': ema50, 'ema200': None}

    return False, {'reason': 'no_clear_trend', 'ema50': ema50, 'ema200': ema200}


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
