"""H3B: with-trend double bottom/top with RSI divergence on 1h (research only).

Frozen protocol: docs/research/h3b_trend_double_bottom_v1/protocol.json.
Uses only closed bars supplied in ``snapshot['recent_bars']``; without them
(e.g. the live builder today) it emits no candidate.
"""
from __future__ import annotations

from types import MappingProxyType

from l2_agents.strategy_engine import (
    StrategyCandidate,
    StrategyPlugin,
    StrategyScan,
    StrategySpec,
)

PIVOT_WIDTH = 3
MIN_SEPARATION, MAX_SEPARATION = 5, 60
EQUAL_ATR = 0.5
MIN_DIVERGENCE = 2.0
MIN_HEIGHT_ATR = 1.0
MAX_BARS_AFTER_P2 = 24
STOP_BUFFER_ATR = 0.25
MIN_RISK_PCT, MAX_RISK_PCT = 1.0, 6.0
TARGET_R = 2.0
MAX_HOLD_MINUTES = 72 * 60
TTL_MINUTES = 15


def ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1)
    out, current = [], values[0]
    for value in values:
        current = alpha * value + (1 - alpha) * current
        out.append(current)
    return out


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder RSI; None until enough history."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, period + 1)]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, period + 1)]
    avg_gain, avg_loss = sum(gains) / period, sum(losses) / period
    for i in range(period, len(closes)):
        if i > period:
            change = closes[i] - closes[i - 1]
            avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    return out


def atr(rows: list[dict], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(rows)
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = float(rows[i]['high']), float(rows[i]['low']), float(rows[i - 1]['close'])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(trs) >= period:
            out[i] = sum(trs[-period:]) / period
    return out


def pivots(values: list[float], kind: str, width: int = PIVOT_WIDTH) -> list[int]:
    """Indices confirmed by ``width`` bars on both sides (last ``width`` bars excluded)."""
    found = []
    for i in range(width, len(values) - width):
        left, right = values[i - width:i], values[i + 1:i + 1 + width]
        if kind == 'low' and values[i] < min(left) and values[i] <= min(right):
            found.append(i)
        if kind == 'high' and values[i] > max(left) and values[i] >= max(right):
            found.append(i)
    return found


def trend_4h(rows_4h: list[dict]) -> str:
    if len(rows_4h) < 60:
        return 'UNKNOWN'
    closes = [float(r['close']) for r in rows_4h]
    e20, e50 = ema(closes, 20)[-1], ema(closes, 50)[-1]
    if closes[-1] > e50 and e20 > e50:
        return 'UP'
    if closes[-1] < e50 and e20 < e50:
        return 'DOWN'
    return 'NONE'


def detect(rows_1h: list[dict], rows_4h: list[dict]) -> dict | None:
    """Return the frozen H3B setup on the last closed 1h bar, or None."""
    if len(rows_1h) < 120:
        return None
    trend = trend_4h(rows_4h)
    if trend not in {'UP', 'DOWN'}:
        return None
    long = trend == 'UP'
    lows = [float(r['low']) for r in rows_1h]
    highs = [float(r['high']) for r in rows_1h]
    closes = [float(r['close']) for r in rows_1h]
    rsis, atrs = rsi(closes), atr(rows_1h)
    last = len(rows_1h) - 1
    extremes = lows if long else highs
    piv = pivots(extremes, 'low' if long else 'high')
    if not piv:
        return None
    p2 = piv[-1]
    if last - p2 > MAX_BARS_AFTER_P2 or last <= p2 or atrs[p2] is None or rsis[p2] is None:
        return None
    a = atrs[p2]
    for p1 in reversed(piv[:-1]):
        gap = p2 - p1
        if gap < MIN_SEPARATION:
            continue
        if gap > MAX_SEPARATION:
            break
        if rsis[p1] is None or abs(extremes[p2] - extremes[p1]) > EQUAL_ATR * a:
            continue
        divergence = (rsis[p2] - rsis[p1]) if long else (rsis[p1] - rsis[p2])
        if divergence < MIN_DIVERGENCE:
            continue
        between = range(p1 + 1, p2)
        if long:
            neckline = max(highs[i] for i in between)
            if neckline - max(lows[p1], lows[p2]) < MIN_HEIGHT_ATR * a:
                continue
            broke = closes[last] > neckline and all(closes[i] <= neckline for i in range(p2 + 1, last))
            stop = min(lows[p1], lows[p2]) - STOP_BUFFER_ATR * a
        else:
            neckline = min(lows[i] for i in between)
            if min(highs[p1], highs[p2]) - neckline < MIN_HEIGHT_ATR * a:
                continue
            broke = closes[last] < neckline and all(closes[i] >= neckline for i in range(p2 + 1, last))
            stop = max(highs[p1], highs[p2]) + STOP_BUFFER_ATR * a
        if not broke:
            return None  # the most recent qualifying pair decides; no stale pairs
        reference = closes[last]
        risk_pct = abs(reference - stop) / reference * 100
        if not MIN_RISK_PCT <= risk_pct <= MAX_RISK_PCT:
            return None
        return {
            'direction': 'LONG' if long else 'SHORT', 'neckline': neckline,
            'reference': reference, 'stop': stop, 'risk_pct': risk_pct,
            'p1': rows_1h[p1]['timestamp'], 'p2': rows_1h[p2]['timestamp'],
            'divergence': divergence, 'trend_4h': trend,
        }
    return None


class H3BTrendDoubleBottom(StrategyPlugin):
    scan_interval = '1h'
    spec = StrategySpec(
        strategy_id='H3B_TREND_DOUBLE_BOTTOM_V1',
        version='h3b-trend-double-bottom-v1.0.0',
        display_name='With-trend double bottom/top + RSI divergence (1h)',
        family='TREND_CONTINUATION',
        status='RESEARCH_ONLY',
        required_timeframes=('4h', '1h', '1m'),
        compatible_management_policies=('P0_INITIAL_STOP',),
        long_zone_kinds=('H3B_NECKLINE',),
        short_zone_kinds=('H3B_NECKLINE',),
        default_ttl_minutes=TTL_MINUTES,
        max_ttl_minutes=TTL_MINUTES,
        detector_mode='MECHANICAL',
        description='4h-trend-aligned 1h double bottom/top with RSI divergence; market entry on the first neckline close.',
    )

    def scan(self, snapshot: dict) -> StrategyScan:
        if not (snapshot.get('data_quality') or {}).get('tradable'):
            return StrategyScan(diagnostics=('Data quality not tradable.',))
        bars = snapshot.get('recent_bars') or {}
        if not bars.get('1h') or not bars.get('4h'):
            return StrategyScan(diagnostics=('H3B needs recent closed 1h/4h bars.',))
        setup = detect(bars['1h'], bars['4h'])
        if setup is None:
            return StrategyScan(diagnostics=('No H3B setup on the last closed 1h bar.',))
        low, high = sorted((setup['neckline'], setup['reference']))
        if low == high:
            return StrategyScan(diagnostics=('Degenerate H3B zone.',))
        return StrategyScan(candidates=(StrategyCandidate(
            strategy_id=self.spec.strategy_id,
            direction=setup['direction'],
            entry_zone=(low, high),
            trigger_conditions=('Market entry at the first 1m close after arming.',),
            invalidation_conditions=('Close beyond the structural stop before entry.',),
            thesis=(f"4h {setup['trend_4h']} trend; 1h double {'bottom' if setup['direction'] == 'LONG' else 'top'}"
                    f" with RSI divergence {setup['divergence']:.1f}; neckline break.",),
            ttl_minutes=TTL_MINUTES,
            metadata=MappingProxyType({'zone_kind': 'H3B_NECKLINE', 'risk_pct': setup['risk_pct'],
                                       'p1': str(setup['p1']), 'p2': str(setup['p2'])}),
            stop_price=setup['stop'],
            target_r=TARGET_R,
            max_hold_minutes=MAX_HOLD_MINUTES,
        ),))

    def triggered(self, plan, candle) -> bool:
        return True  # market entry; the resolver checks pre-invalidation first


STRATEGY_PLUGIN = H3BTrendDoubleBottom()
