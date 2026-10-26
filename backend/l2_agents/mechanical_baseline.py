"""No-AI control arm: one fixed rule on the same snapshots the AI sees.

The AI adjudicator only earns its cost if its plans beat this rule on the
identical bars, costs and resolver. The rule is deliberately simple and frozen;
changing it starts a new ``BASELINE_VERSION``.
"""
from __future__ import annotations

from .auction_adjudicator import AuctionAdjudicator, AuctionDecision

BASELINE_VERSION = 'sai1-mechanical-v1'
MAX_ZONE_DISTANCE_ATR = 2.0
BASELINE_TTL_MINUTES = 60


def _pass(snapshot: dict, reason: str) -> AuctionDecision:
    quality = snapshot.get('data_quality') or {}
    return AuctionDecision(
        action='PASS', direction='NONE', strategy_id='NONE',
        confidence=1.0, data_quality=float(quality.get('score') or 0.0),
        thesis=[], counter_thesis=[reason], entry_zone=None,
        trigger_conditions=[], invalidation_conditions=[],
        management_policy='NONE', ttl_minutes=0,
        recheck_condition='Next closed 15m bar.', risk_notes=['Mechanical baseline.'],
    )


def mechanical_decision(snapshot: dict) -> AuctionDecision:
    """Failed auction at the 20-bar extreme on the side the regime allows.

    TREND_UP longs a sweep-and-reclaim of support, TREND_DOWN shorts a
    sweep-and-reject of resistance, RANGE takes whichever extreme is nearer,
    TRANSITION passes. The extreme must lie within 2x 15m ATR of the close.
    """
    if not (snapshot.get('data_quality') or {}).get('tradable'):
        return _pass(snapshot, 'Data quality not tradable.')
    regime = (snapshot.get('global_regime') or {}).get('state')
    tf15 = (snapshot.get('instrument') or {}).get('15m') or {}
    close = tf15.get('close')
    atr = tf15.get('atr14')
    if not close or not atr or atr <= 0:
        return _pass(snapshot, 'Missing 15m close or ATR.')

    zones = {zone['kind']: zone for zone in snapshot.get('zones') or []}
    support = zones.get('RECENT_SUPPORT')
    resistance = zones.get('RECENT_RESISTANCE')
    candidates = []
    if support and regime in {'TREND_UP', 'RANGE'}:
        candidates.append(('LONG', support, (close - support['high']) / atr))
    if resistance and regime in {'TREND_DOWN', 'RANGE'}:
        candidates.append(('SHORT', resistance, (resistance['low'] - close) / atr))
    candidates = [c for c in candidates if 0 <= c[2] <= MAX_ZONE_DISTANCE_ATR]
    if not candidates:
        return _pass(snapshot, f'No regime-aligned extreme within 2 ATR ({regime}).')

    direction, zone, distance = min(candidates, key=lambda c: c[2])
    low, high = float(zone['low']), float(zone['high'])
    if direction == 'LONG':
        trigger = f'1m close above {high} after trading below {low}'
        invalidation = 'Structural stop below the swept support'
    else:
        trigger = f'1m close below {low} after trading above {high}'
        invalidation = 'Structural stop above the swept resistance'
    decision = AuctionDecision(
        action='ARM', direction=direction, strategy_id='SAI1_FAILED_AUCTION',
        confidence=0.5, data_quality=float(snapshot['data_quality'].get('score') or 0.0),
        thesis=[f'{regime} regime; 20-bar extreme {distance:.2f} ATR away.'],
        counter_thesis=['Extreme may break and trend through.'],
        entry_zone=[low, high], trigger_conditions=[trigger],
        invalidation_conditions=[invalidation],
        management_policy='P0_INITIAL_STOP', ttl_minutes=BASELINE_TTL_MINUTES,
        recheck_condition='Next closed 15m bar.', risk_notes=['Mechanical baseline.'],
    )
    # Same authority checks as the AI, so both arms obey one contract.
    AuctionAdjudicator._validate_against_snapshot(decision, snapshot)
    return decision
