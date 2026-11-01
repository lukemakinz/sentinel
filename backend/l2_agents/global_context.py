"""Replayable, non-executable global crypto market context.

The first version deliberately uses only data already collected by Sentinel:
BTC/ETH trends, relative performance and internal alt breadth.  External
market-cap and dominance indices have explicit unavailable slots until a
licensed, replayable provider is configured.  They must never be silently
replaced with an unlabeled proxy.
"""
from __future__ import annotations

from datetime import datetime, timedelta


GLOBAL_CONTEXT_VERSION = 'global-context-v1.3-fresh-breadth20'
# Breadth from fewer independent alts is anecdote, not breadth.  The target
# itself is always excluded so the context never feeds on its own chart.
MIN_BREADTH_SYMBOLS = 5
MIN_TREND_BARS = 50
BREADTH_MAX_CLOSE_AGE = timedelta(hours=2)
EXTERNAL_INDICATORS = (
    'TOTAL', 'TOTAL2', 'TOTAL3', 'TOTAL3ES', 'BTC.D',
)

_TREND_SIGN = {'UP': 1.0, 'DOWN': -1.0, 'RANGE': 0.0}


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(float(value), high))


def _weighted(values: list[tuple[float | None, float]]) -> tuple[float | None, float]:
    available = [(value, weight) for value, weight in values if value is not None]
    total_available = sum(weight for _value, weight in available)
    total_possible = sum(weight for _value, weight in values)
    if not available or total_available <= 0:
        return None, 0.0
    score = sum(float(value) * weight for value, weight in available) / total_available
    coverage = total_available / total_possible if total_possible else 0.0
    return _clip(score), round(coverage, 4)


def _timestamp(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def _frame_issue(frame: dict, interval: str, as_of: datetime | None) -> str | None:
    if not frame.get('available'):
        return 'missing'
    bars = frame.get('bars')
    if bars is not None and int(bars) < MIN_TREND_BARS:
        return 'insufficient_history'
    if frame.get('trend') not in _TREND_SIGN:
        return 'unknown_trend'
    if as_of is not None:
        opened_at = _timestamp(frame.get('last_timestamp'))
        if opened_at is None:
            return 'missing_timestamp'
        interval_hours = {'1h': 1, '4h': 4}.get(interval)
        if interval_hours is None:
            return 'unsupported_interval'
        closed_at = opened_at + timedelta(hours=interval_hours)
        max_age = BREADTH_MAX_CLOSE_AGE if interval == '1h' else timedelta(hours=8)
        if as_of - closed_at > max_age:
            return 'stale'
    return None


def _trend_value(frames: dict, interval: str,
                 as_of: datetime | None) -> float | None:
    frame = frames.get(interval) or {}
    return None if _frame_issue(frame, interval, as_of) else _TREND_SIGN[frame['trend']]


def _trend_score(frames: dict, as_of: datetime | None) -> tuple[float | None, float]:
    return _weighted([
        (_trend_value(frames, '1h', as_of), 0.35),
        (_trend_value(frames, '4h', as_of), 0.65),
    ])


def _relative_eth_btc(symbol_summaries: dict,
                      as_of: datetime | None) -> float | None:
    """Bounded 20-hour ETH-vs-BTC return proxy, explicitly labeled as such."""
    eth_frame = symbol_summaries.get('ETHUSDT', {}).get('1h') or {}
    btc_frame = symbol_summaries.get('BTCUSDT', {}).get('1h') or {}
    if (_frame_issue(eth_frame, '1h', as_of)
            or _frame_issue(btc_frame, '1h', as_of)):
        return None
    eth_return = eth_frame.get('return_20_pct')
    btc_return = btc_frame.get('return_20_pct')
    if eth_return is None or btc_return is None:
        return None
    # A three percentage-point relative move maps to a full-scale score.
    return _clip((float(eth_return) - float(btc_return)) / 3.0)


def _breadth(symbol_summaries: dict, target_symbol: str,
             universe: list[str] | None = None,
             as_of: datetime | None = None) -> dict:
    # With a frozen universe, breadth is exactly that list (replayable);
    # adding a watched pair later must not silently change the index.
    allowed = {s.upper() for s in universe} if universe else set(symbol_summaries)
    symbols = sorted(allowed - {'BTCUSDT', 'ETHUSDT', target_symbol})
    known = []
    issue_counts: dict[str, int] = {}
    for symbol in symbols:
        frame = (symbol_summaries.get(symbol, {}).get('1h') or {})
        issue = _frame_issue(frame, '1h', as_of)
        if issue:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
            continue
        known.append(frame['trend'])
    if len(known) < MIN_BREADTH_SYMBOLS:
        return {
            'available': False, 'symbols': len(known), 'up_share': None,
            'down_share': None, 'net_score_minus1_1': None,
            'reason': f'needs_{MIN_BREADTH_SYMBOLS}_alts_excluding_target',
            'universe_symbols': len(symbols),
            'excluded_by_quality': issue_counts,
        }
    up = sum(value == 'UP' for value in known)
    down = sum(value == 'DOWN' for value in known)
    count = len(known)
    return {
        'available': True,
        'symbols': count,
        'up_share': round(up / count, 4),
        'down_share': round(down / count, 4),
        'net_score_minus1_1': round((up - down) / count, 4),
        'universe_symbols': len(symbols),
        'excluded_by_quality': issue_counts,
    }


def _external_contract() -> dict:
    return {
        indicator: {
            'available': False,
            'source': None,
            'source_version': None,
            'reason': 'replayable_external_provider_not_configured',
            'used_in_score': False,
        }
        for indicator in EXTERNAL_INDICATORS
    }


def build_global_context(symbol_summaries: dict, target_symbol: str,
                         breadth_universe: dict | None = None,
                         as_of: datetime | None = None) -> dict:
    """Build one deterministic top-down context for a target instrument."""
    target_symbol = target_symbol.upper()
    btc_score, btc_coverage = _trend_score(
        symbol_summaries.get('BTCUSDT', {}), as_of,
    )
    eth_score, eth_coverage = _trend_score(
        symbol_summaries.get('ETHUSDT', {}), as_of,
    )
    breadth = _breadth(symbol_summaries, target_symbol,
                       (breadth_universe or {}).get('symbols'), as_of)
    relative_score = _relative_eth_btc(symbol_summaries, as_of)

    alt_score, alt_coverage = _weighted([
        (btc_score, 0.20),
        (eth_score, 0.20),
        (breadth.get('net_score_minus1_1'), 0.40),
        (relative_score, 0.20),
    ])
    if target_symbol == 'BTCUSDT':
        target_score, target_coverage, target_class = btc_score, btc_coverage, 'BTC'
    elif target_symbol == 'ETHUSDT':
        target_score, target_coverage = _weighted([
            (btc_score, 0.30), (eth_score, 0.55), (relative_score, 0.15),
        ])
        target_class = 'ETH'
    else:
        target_score, target_coverage, target_class = alt_score, alt_coverage, 'ALT'

    if alt_score is None:
        state = 'UNKNOWN'
    elif btc_score is not None and btc_score >= 0.40 and alt_score <= -0.20:
        state = 'BTC_LED_ALT_HEADWIND'
    elif alt_score >= 0.35:
        state = 'ALT_RISK_ON'
    elif alt_score <= -0.35:
        state = 'ALT_RISK_OFF'
    elif btc_score is not None and btc_score <= -0.35:
        state = 'BROAD_RISK_OFF'
    else:
        state = 'TRANSITION'

    return {
        'version': GLOBAL_CONTEXT_VERSION,
        'state': state,
        'target_symbol': target_symbol,
        'target_class': target_class,
        'target_bias_score_minus100_100': (
            round(target_score * 100.0, 2) if target_score is not None else None
        ),
        'target_data_coverage_0_1': target_coverage,
        'as_of': as_of.isoformat() if as_of is not None else None,
        'components': {
            'btc_trend_score_minus1_1': (
                round(btc_score, 4) if btc_score is not None else None
            ),
            'btc_trend_coverage_0_1': btc_coverage,
            'eth_trend_score_minus1_1': (
                round(eth_score, 4) if eth_score is not None else None
            ),
            'eth_trend_coverage_0_1': eth_coverage,
            'eth_vs_btc_20h_return_proxy_minus1_1': (
                round(relative_score, 4) if relative_score is not None else None
            ),
            'alt_breadth_1h': breadth,
            'alt_context_score_minus1_1': (
                round(alt_score, 4) if alt_score is not None else None
            ),
            'alt_context_coverage_0_1': alt_coverage,
        },
        'breadth_universe': breadth_universe or {'version': None, 'symbols': []},
        'external_indicators': _external_contract(),
        'external_data_used': False,
        'learning_only': True,
        'execution_authorized': False,
        'guardrail': (
            'Descriptive internal context only. External TOTAL/dominance data '
            'is unavailable and is not inferred or scraped.'
        ),
    }


def candidate_alignment(context: dict, direction: str) -> dict:
    """Describe alignment without claiming the context caused an outcome."""
    score = context.get('target_bias_score_minus100_100')
    coverage = float(context.get('target_data_coverage_0_1') or 0.0)
    if score is None or direction not in {'LONG', 'SHORT'}:
        return {
            'status': 'UNKNOWN', 'aligned_score_minus1_1': None,
            'data_coverage_0_1': coverage,
        }
    aligned = float(score) / 100.0 * (1.0 if direction == 'LONG' else -1.0)
    status = 'ALIGNED' if aligned >= 0.25 else 'OPPOSED' if aligned <= -0.25 else 'NEUTRAL'
    return {
        'status': status,
        'aligned_score_minus1_1': round(aligned, 4),
        'data_coverage_0_1': coverage,
    }
