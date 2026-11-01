"""Deterministic, replayable multi-timeframe trend classification.

The engine is deliberately descriptive.  It never authorizes execution and it
uses only closed OHLCV rows already present in a market snapshot build.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime


TREND_STATE_VERSION = 'trend-state-v1'
TIMEFRAME_WEIGHTS = {
    '5m': 0.10,
    '15m': 0.15,
    '1h': 0.25,
    '4h': 0.30,
    '1d': 0.20,
}


def _round(value, digits=6):
    return round(float(value), digits) if value is not None else None


def _iso(value):
    if value is None:
        return None
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result


def _atr_series(rows: list[dict], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(rows)
    ranges = []
    for index in range(1, len(rows)):
        high = float(rows[index]['high'])
        low = float(rows[index]['low'])
        previous_close = float(rows[index - 1]['close'])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        if len(ranges) >= period:
            result[index] = sum(ranges[-period:]) / period
    return result


def _structure(rows: list[dict]) -> str:
    if len(rows) < 20:
        return 'UNKNOWN'
    previous, current = rows[-20:-10], rows[-10:]
    previous_high = max(float(row['high']) for row in previous)
    previous_low = min(float(row['low']) for row in previous)
    current_high = max(float(row['high']) for row in current)
    current_low = min(float(row['low']) for row in current)
    if current_high > previous_high and current_low > previous_low:
        return 'HH_HL'
    if current_high < previous_high and current_low < previous_low:
        return 'LH_LL'
    return 'MIXED'


def classify_timeframe(rows: list[dict], interval: str) -> dict:
    """Classify one timeframe without looking beyond the supplied rows."""
    if len(rows) < 20:
        return {
            'available': False,
            'interval': interval,
            'bars': len(rows),
            'direction': 'UNKNOWN',
            'strength_0_100': 0.0,
            'structure': 'UNKNOWN',
            'reason': 'Need at least 20 closed bars.',
        }

    closes = [float(row['close']) for row in rows]
    ema_fast_series = _ema(closes, 20)
    ema_slow_series = _ema(closes, 50)
    atr_series = _atr_series(rows)
    atr = atr_series[-1]
    if atr is None or atr <= 0:
        return {
            'available': False,
            'interval': interval,
            'bars': len(rows),
            'last_timestamp': _iso(rows[-1]['timestamp']),
            'direction': 'UNKNOWN',
            'strength_0_100': 0.0,
            'structure': _structure(rows),
            'reason': 'ATR is unavailable or zero.',
        }

    close = closes[-1]
    ema_fast = ema_fast_series[-1]
    ema_slow = ema_slow_series[-1]
    lookback = min(5, len(ema_fast_series) - 1)
    slope_atr = (
        (ema_fast - ema_fast_series[-1 - lookback]) / (lookback * atr)
        if lookback else 0.0
    )
    separation_atr = (ema_fast - ema_slow) / atr
    structure = _structure(rows)

    direction = 'RANGE'
    if close > ema_fast > ema_slow and slope_atr > 0.02:
        direction = 'UP'
    elif close < ema_fast < ema_slow and slope_atr < -0.02:
        direction = 'DOWN'

    structure_aligned = (
        (direction == 'UP' and structure == 'HH_HL')
        or (direction == 'DOWN' and structure == 'LH_LL')
    )
    raw_strength = (
        0.50 * min(abs(separation_atr) / 1.5, 1.0)
        + 0.30 * min(abs(slope_atr) / 0.20, 1.0)
        + 0.20 * float(structure_aligned)
    )
    if direction == 'RANGE':
        raw_strength = min(raw_strength, 0.49)

    available_atrs = [value for value in atr_series if value is not None]
    volatility_percentile = (
        100.0 * sum(value <= atr for value in available_atrs) / len(available_atrs)
        if available_atrs else None
    )
    return {
        'available': True,
        'interval': interval,
        'bars': len(rows),
        'last_timestamp': _iso(rows[-1]['timestamp']),
        'direction': direction,
        'strength_0_100': _round(raw_strength * 100.0, 2),
        'structure': structure,
        'close': _round(close),
        'ema20': _round(ema_fast),
        'ema50': _round(ema_slow),
        'ema_separation_atr': _round(separation_atr, 4),
        'ema20_slope_atr_per_bar': _round(slope_atr, 4),
        'atr14': _round(atr),
        'volatility_percentile_0_100': _round(volatility_percentile, 2),
    }


def derive_closed_daily_rows(rows_4h: list[dict]) -> list[dict]:
    """Aggregate only complete UTC days made of six closed 4h bars."""
    grouped: dict[object, list[dict]] = defaultdict(list)
    for row in rows_4h:
        timestamp = row.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if timestamp is not None:
            grouped[timestamp.date()].append({**row, 'timestamp': timestamp})

    daily = []
    expected_hours = {0, 4, 8, 12, 16, 20}
    for day in sorted(grouped):
        bars = sorted(grouped[day], key=lambda row: row['timestamp'])
        if len(bars) != 6 or {row['timestamp'].hour for row in bars} != expected_hours:
            continue
        daily.append({
            'timestamp': bars[0]['timestamp'].replace(hour=0, minute=0, second=0, microsecond=0),
            'open': bars[0]['open'],
            'high': max(float(row['high']) for row in bars),
            'low': min(float(row['low']) for row in bars),
            'close': bars[-1]['close'],
            'volume': sum(float(row['volume']) for row in bars),
        })
    return daily


def build_trend_state(timeframes: dict) -> dict:
    """Return one versioned trend state for 5m/15m/1h/4h/1d."""
    states = {}
    for interval in TIMEFRAME_WEIGHTS:
        frame = timeframes.get(interval) or {}
        rows = frame.get('_recent_rows') or []
        states[interval] = classify_timeframe(rows, interval)
        if interval == '1d' and frame.get('source'):
            states[interval]['source'] = frame['source']

    available = {
        interval: state for interval, state in states.items()
        if state.get('available') and state.get('direction') != 'UNKNOWN'
    }
    weight_total = sum(TIMEFRAME_WEIGHTS[key] for key in available)
    signed = {'UP': 1.0, 'DOWN': -1.0, 'RANGE': 0.0, 'UNKNOWN': 0.0}
    score = 0.0
    if weight_total:
        score = sum(
            TIMEFRAME_WEIGHTS[key]
            * signed[state['direction']]
            * float(state['strength_0_100']) / 100.0
            for key, state in available.items()
        ) / weight_total

    coverage = weight_total / sum(TIMEFRAME_WEIGHTS.values())
    if len(available) < 3 or not states['4h'].get('available'):
        alignment = 'INSUFFICIENT'
        regime = 'INSUFFICIENT'
        bias = 'NEUTRAL'
    elif score >= 0.35:
        alignment, regime, bias = 'ALIGNED_UP', 'UPTREND', 'LONG'
    elif score <= -0.35:
        alignment, regime, bias = 'ALIGNED_DOWN', 'DOWNTREND', 'SHORT'
    elif abs(score) <= 0.12:
        alignment, regime, bias = 'RANGE', 'RANGE', 'NEUTRAL'
    else:
        alignment, regime, bias = 'CONFLICT', 'CONFLICT', 'NEUTRAL'

    return {
        'version': TREND_STATE_VERSION,
        'learning_only': True,
        'execution_authorized': False,
        'regime': regime,
        'directional_bias': bias,
        'alignment': alignment,
        'alignment_score_minus100_100': _round(score * 100.0, 2),
        'coverage_0_1': _round(coverage, 2),
        'timeframes': states,
    }
