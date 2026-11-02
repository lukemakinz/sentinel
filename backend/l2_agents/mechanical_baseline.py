"""No-AI control arm: one fixed rule on the same snapshots the AI sees.

The AI adjudicator only earns its cost if its plans beat this rule on the
identical bars, costs and resolver. The rule is deliberately simple and frozen;
changing it starts a new ``BASELINE_VERSION``.
"""
from __future__ import annotations

from .auction_adjudicator import AuctionAdjudicator, AuctionDecision
from .strategies import strategy_registry
from .strategies.failed_auction import MAX_ZONE_DISTANCE_ATR

BASELINE_VERSION = 'sai1-mechanical-v1'
TREND_FILTER_VERSION = 'sai1-mechanical-trend-filter-v1'
GLOBAL_CONTEXT_FILTER_VERSION = 'sai1-global-context-filter-v1'
BASELINE_TTL_MINUTES = strategy_registry.get(
    'SAI1_FAILED_AUCTION',
).spec.default_ttl_minutes
GLOBAL_CONTEXT_MIN_COVERAGE = 0.75
GLOBAL_CONTEXT_VETO_THRESHOLD = -0.45


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
    if 'SAI1_FAILED_AUCTION' not in (snapshot.get('strategy_registry') or {}):
        return _pass(snapshot, 'SAI1_FAILED_AUCTION is disabled for new plans.')
    scan = strategy_registry.scan(
        snapshot, strategy_ids=('SAI1_FAILED_AUCTION',),
    )
    if not scan.candidates:
        reason = scan.diagnostics[0] if scan.diagnostics else 'No mechanical candidate.'
        return _pass(snapshot, reason)

    candidate = scan.candidates[0]
    low, high = candidate.entry_zone
    decision = AuctionDecision(
        action='ARM', direction=candidate.direction,
        strategy_id=candidate.strategy_id,
        confidence=0.5, data_quality=float(snapshot['data_quality'].get('score') or 0.0),
        thesis=list(candidate.thesis),
        counter_thesis=['Extreme may break and trend through.'],
        entry_zone=[low, high],
        trigger_conditions=list(candidate.trigger_conditions),
        invalidation_conditions=list(candidate.invalidation_conditions),
        management_policy='P0_INITIAL_STOP', ttl_minutes=candidate.ttl_minutes,
        recheck_condition='Next closed 15m bar.', risk_notes=['Mechanical baseline.'],
    )
    # Same authority checks as the AI, so both arms obey one contract.
    AuctionAdjudicator._validate_against_snapshot(decision, snapshot)
    return decision


def trend_alignment_score(snapshot: dict, direction: str) -> tuple[float | None, list[str]]:
    """Frozen M1 score in [-1, 1] for ``direction``; None without 4h + one of 1h/1d."""
    states = (snapshot.get('trend_state') or {}).get('timeframes') or {}
    weights = {'1h': 0.25, '4h': 0.45, '1d': 0.30}
    signs = {'UP': 1.0, 'DOWN': -1.0, 'RANGE': 0.0}
    available = {
        interval: state for interval, state in states.items()
        if interval in weights and state.get('available')
        and state.get('direction') in signs
    }
    if len(available) < 2 or '4h' not in available:
        return None, sorted(available)
    weight_total = sum(weights[interval] for interval in available)
    market_score = sum(
        weights[interval] * signs[state['direction']]
        * float(state.get('strength_0_100') or 0.0) / 100.0
        for interval, state in available.items()
    ) / weight_total
    return (1.0 if direction == 'LONG' else -1.0) * market_score, sorted(available)


def trend_filtered_decision(
    snapshot: dict, baseline: AuctionDecision | None = None,
) -> AuctionDecision:
    """M1: keep an M0 candidate unless the higher-timeframe trend opposes it.

    The frozen score uses 1h/4h/1d directional strength with weights
    25%/45%/30%.  At least two timeframes including 4h must be known.  An M0
    candidate is vetoed only when its aligned score is below -0.25.
    """
    baseline = baseline or mechanical_decision(snapshot)
    if baseline.action != 'ARM':
        return baseline

    aligned_score, available = trend_alignment_score(snapshot, baseline.direction)
    if aligned_score is None:
        return _trend_filter_pass(
            snapshot, 'M1 requires 4h and at least one of 1h/1d trend states.',
        )
    evidence = (
        f'M1 higher-timeframe aligned score {aligned_score:+.3f} '
        f'(minimum -0.250; {", ".join(sorted(available))}).'
    )
    if aligned_score < -0.25:
        return _trend_filter_pass(snapshot, evidence + ' Candidate vetoed.')

    payload = baseline.model_dump()
    payload['thesis'] = [*payload['thesis'], evidence]
    payload['risk_notes'] = [
        *payload['risk_notes'],
        f'Deterministic research filter {TREND_FILTER_VERSION}; no execution authority.',
    ]
    return AuctionDecision(**payload)


def _trend_filter_pass(snapshot: dict, reason: str) -> AuctionDecision:
    quality = snapshot.get('data_quality') or {}
    return AuctionDecision(
        action='PASS', direction='NONE', strategy_id='NONE',
        confidence=1.0, data_quality=float(quality.get('score') or 0.0),
        thesis=[], counter_thesis=[reason], entry_zone=None,
        trigger_conditions=[], invalidation_conditions=[],
        management_policy='NONE', ttl_minutes=0,
        recheck_condition='Evaluate the next new mechanical candidate episode.',
        risk_notes=[
            f'Deterministic research filter {TREND_FILTER_VERSION}; no execution authority.',
        ],
    )


def global_context_filtered_decision(
    snapshot: dict, baseline: AuctionDecision | None = None,
) -> AuctionDecision:
    """M3: prospective global-context overlay on the unchanged M0 geometry.

    The symmetric -0.45 veto and 0.75 coverage floor are frozen engineering
    constraints, not thresholds fitted to the current four filled plans.
    Missing context fails this research policy closed.  The external TOTAL and
    dominance slots are descriptive-only in v1 and are not required or faked.
    """
    baseline = baseline or mechanical_decision(snapshot)
    if baseline.action != 'ARM':
        return baseline
    assessment = global_context_filter_assessment(snapshot, baseline.direction)
    coverage = assessment['coverage_0_1']
    aligned_score = assessment['aligned_score_minus1_1']
    if assessment['reason_code'] == 'DATA_INELIGIBLE':
        return _global_context_pass(
            snapshot,
            f'M3 global context unavailable or incomplete (coverage {coverage:.2f}).',
            reason_code='DATA_INELIGIBLE',
        )

    evidence = (
        f'M3 global aligned score {aligned_score:+.3f} '
        f'(veto below {GLOBAL_CONTEXT_VETO_THRESHOLD:+.3f}; '
        f'coverage {coverage:.2f}; state {assessment["state"]}).'
    )
    if assessment['reason_code'] == 'GLOBAL_HEADWIND_VETO':
        return _global_context_pass(
            snapshot, evidence + ' Candidate vetoed.',
            reason_code='GLOBAL_HEADWIND_VETO',
        )

    payload = baseline.model_dump()
    payload['thesis'] = [*payload['thesis'], evidence]
    payload['risk_notes'] = [
        *payload['risk_notes'],
        'M3_REASON_CODE=CONTEXT_KEEP',
        f'Deterministic research filter {GLOBAL_CONTEXT_FILTER_VERSION}; '
        'external TOTAL/dominance data not used in v1; no execution authority.',
    ]
    return AuctionDecision(**payload)


def global_context_filter_assessment(snapshot: dict, direction: str) -> dict:
    """Return a stable reason code so missing data is not called a smart veto."""
    from .global_context import candidate_alignment

    context = snapshot.get('global_context') or {}
    alignment = candidate_alignment(context, direction)
    coverage = float(alignment.get('data_coverage_0_1') or 0.0)
    aligned_score = alignment.get('aligned_score_minus1_1')
    if aligned_score is None or coverage < GLOBAL_CONTEXT_MIN_COVERAGE:
        reason_code = 'DATA_INELIGIBLE'
    elif float(aligned_score) < GLOBAL_CONTEXT_VETO_THRESHOLD:
        reason_code = 'GLOBAL_HEADWIND_VETO'
    else:
        reason_code = 'CONTEXT_KEEP'
    return {
        'reason_code': reason_code,
        'aligned_score_minus1_1': (
            float(aligned_score) if aligned_score is not None else None
        ),
        'coverage_0_1': coverage,
        'state': context.get('state', 'UNKNOWN'),
    }


def _global_context_pass(snapshot: dict, reason: str,
                         reason_code: str) -> AuctionDecision:
    quality = snapshot.get('data_quality') or {}
    return AuctionDecision(
        action='PASS', direction='NONE', strategy_id='NONE',
        confidence=1.0, data_quality=float(quality.get('score') or 0.0),
        thesis=[], counter_thesis=[reason], entry_zone=None,
        trigger_conditions=[], invalidation_conditions=[],
        management_policy='NONE', ttl_minutes=0,
        recheck_condition='Evaluate the next new mechanical candidate episode.',
        risk_notes=[
            f'M3_REASON_CODE={reason_code}',
            f'Deterministic research filter {GLOBAL_CONTEXT_FILTER_VERSION}; '
            'no execution authority.',
        ],
    )
