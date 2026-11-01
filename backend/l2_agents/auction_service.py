"""One fail-closed service for CLI and scheduled auction analysis."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .auction_adjudicator import (
    AUCTION_PROMPT_VERSION,
    AdjudicationError,
    AuctionAdjudicator,
    AuctionDecision,
    unavailable_analysis_cost,
    zero_analysis_cost,
)
from .market_intelligence import MarketSnapshotBuilder, deterministic_preflight
from .models import AuctionAnalysis, AuctionCandidate


def analysis_cycle_key(snapshot: dict, use_ai: bool, mode: str | None = None) -> str:
    """Return one stable key per symbol/closed 15m bar and analysis mode."""
    bar_timestamp = snapshot.get('instrument', {}).get('15m', {}).get('last_timestamp')
    if not bar_timestamp:
        try:
            as_of = datetime.fromisoformat(snapshot['as_of'].replace('Z', '+00:00'))
            bar_timestamp = as_of.replace(
                minute=(as_of.minute // 15) * 15, second=0, microsecond=0,
            ).isoformat()
        except (KeyError, TypeError, ValueError):
            bar_timestamp = 'missing'
    raw = ':'.join((
        snapshot.get('version', ''), snapshot.get('symbol', ''), bar_timestamp,
        'ready' if snapshot.get('data_quality', {}).get('tradable') else 'unready',
        mode or ('ai' if use_ai else 'deterministic'), AUCTION_PROMPT_VERSION,
    ))
    return sha256(raw.encode()).hexdigest()


def ai_spend_since(since) -> Decimal:
    """Sum known AI cost of persisted analyses created at or after ``since``."""
    total = Decimal('0')
    for runtime in AuctionAnalysis.objects.filter(
        timestamp__gte=since,
    ).values_list('runtime', flat=True):
        cost = (runtime or {}).get('analysis_cost') or {}
        if cost.get('estimated_usd') is not None:
            total += Decimal(str(cost['estimated_usd']))
    return total


def ai_budget_status() -> dict:
    """Today's (UTC) persisted AI spend against the configured daily cap."""
    start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    budget = Decimal(str(getattr(settings, 'AUCTION_AI_DAILY_BUDGET_USD', 1.0)))
    spent = ai_spend_since(start)
    return {
        'daily_budget_usd': float(budget),
        'spent_today_usd': float(spent),
        'remaining_today_usd': float(max(budget - spent, Decimal('0'))),
        'spent_last_7_days_usd': float(ai_spend_since(start - timedelta(days=6))),
        'exhausted': spent >= budget,
    }


def _fail_closed(snapshot: dict, reason: str, runtime: dict) -> tuple[AuctionDecision, dict]:
    base = deterministic_preflight(snapshot)
    base.update({
        'action': 'PASS', 'direction': 'NONE', 'strategy_id': 'NONE',
        'counter_thesis': [reason],
        'recheck_condition': 'Inspect the recorded runtime and rerun in shadow mode.',
        'risk_notes': ['No execution authorized.'],
    })
    return AuctionDecision(**base), {
        'provider': None, 'model': None,
        'prompt_version': AUCTION_PROMPT_VERSION,
        **runtime,
    }


CANDIDATE_REUSE = timedelta(hours=4)


def mechanical_candidate(snapshot: dict) -> dict | None:
    """The deterministic gate: only what the frozen baseline would ARM."""
    from .mechanical_baseline import mechanical_decision

    try:
        decision = mechanical_decision(snapshot)
    except ValueError:
        return None
    if decision.action != 'ARM':
        return None
    low, high = sorted(float(v) for v in decision.entry_zone)
    return {
        'strategy_id': decision.strategy_id,
        'direction': decision.direction,
        'entry_zone': [low, high],
        'management_policy': decision.management_policy,
        'thesis': decision.thesis,
        'key': f"{snapshot.get('symbol')}:{decision.direction}:{decision.strategy_id}:{low:.10g}:{high:.10g}",
    }


def _candidate_episode(candidate: dict) -> AuctionCandidate:
    """Return the single active episode for candidate geometry."""
    now = timezone.now()
    fingerprint = candidate['key']
    for _attempt in range(2):
        with transaction.atomic():
            active = (AuctionCandidate.objects.select_for_update()
                      .filter(active_fingerprint=fingerprint).first())
            if active is not None and active.adjudication_expires_at > now:
                return active
            if active is not None:
                active.active_fingerprint = None
                active.save(update_fields=['active_fingerprint'])
        try:
            with transaction.atomic():
                return AuctionCandidate.objects.create(
                    fingerprint=fingerprint,
                    active_fingerprint=fingerprint,
                    symbol=fingerprint.split(':', 1)[0],
                    direction=candidate['direction'],
                    strategy_id=candidate['strategy_id'],
                    entry_zone=candidate['entry_zone'],
                    first_seen_at=now,
                    adjudication_expires_at=now + CANDIDATE_REUSE,
                )
        except IntegrityError:
            # Another worker won the unique active-fingerprint race.
            continue
    return AuctionCandidate.objects.get(active_fingerprint=fingerprint)


def _attach_baseline(candidate: AuctionCandidate, analysis: AuctionAnalysis) -> bool:
    """Attach exactly one outcome plan to a candidate episode."""
    with transaction.atomic():
        locked = AuctionCandidate.objects.select_for_update().get(pk=candidate.pk)
        if locked.baseline_analysis_id is not None:
            return False
        locked.baseline_analysis = analysis
        locked.save(update_fields=['baseline_analysis'])
        from .shadow_auction import create_shadow_plan
        create_shadow_plan(analysis)
        return True


def _attach_ai(candidate: AuctionCandidate, analysis: AuctionAnalysis) -> bool:
    """Attach the first valid, actually model-produced verdict to the episode."""
    runtime = analysis.runtime or {}
    if analysis.provider not in {'openai', 'anthropic'} or runtime.get('error_type'):
        return False
    with transaction.atomic():
        locked = AuctionCandidate.objects.select_for_update().get(pk=candidate.pk)
        if locked.ai_analysis_id is not None:
            return False
        locked.ai_analysis = analysis
        locked.save(update_fields=['ai_analysis'])
        return True


def _attach_trend_filter(candidate: AuctionCandidate, analysis: AuctionAnalysis) -> bool:
    """Attach exactly one prospective M1 verdict to a new candidate episode."""
    with transaction.atomic():
        locked = AuctionCandidate.objects.select_for_update().get(pk=candidate.pk)
        if locked.trend_filter_analysis_id is not None:
            return False
        locked.trend_filter_analysis = analysis
        locked.save(update_fields=['trend_filter_analysis'])
        return True


def _attach_global_context(candidate: AuctionCandidate, analysis: AuctionAnalysis) -> bool:
    """Attach exactly one prospective M3 verdict to a new candidate episode."""
    with transaction.atomic():
        locked = AuctionCandidate.objects.select_for_update().get(pk=candidate.pk)
        if locked.global_context_analysis_id is not None:
            return False
        locked.global_context_analysis = analysis
        locked.save(update_fields=['global_context_analysis'])
        return True


def _recent_adjudication(candidate_key: str):
    """Latest real (billed or valid) AI verdict on this candidate within 4h.

    Reuse rows never extend the window, and an API error without usage may be
    retried, so the same candidate is paid for at most once per window.
    """
    rows = (AuctionAnalysis.objects
            .filter(runtime__candidate_key=candidate_key,
                    timestamp__gte=timezone.now() - CANDIDATE_REUSE)
            .order_by('-timestamp'))
    for row in rows:
        runtime = row.runtime or {}
        if runtime.get('reason') == 'candidate_already_adjudicated':
            continue
        if (runtime.get('analysis_cost') or {}).get('estimated_usd') is None \
                and runtime.get('error_type'):
            continue
        return row
    return None


def decide_snapshot(snapshot: dict, use_ai: bool,
                    episode: AuctionCandidate | None = None) -> tuple[AuctionDecision, dict]:
    """Adjudicate one already-built immutable snapshot and always fail closed."""
    if use_ai:
        preflight = deterministic_preflight(snapshot)
        candidate = mechanical_candidate(snapshot) if preflight['action'] != 'PASS' else None
        if candidate is None:
            # No deterministic candidate: nothing for the model to judge.
            return AuctionDecision(**preflight), {
                'provider': None, 'model': None,
                'prompt_version': AUCTION_PROMPT_VERSION,
                'reason': 'no_mechanical_candidate',
                'analysis_cost': zero_analysis_cost('no_mechanical_candidate'),
            }
        previous = episode.ai_analysis if episode and episode.ai_analysis_id else None
        if previous is None and episode is None:
            previous = _recent_adjudication(candidate['key'])
        if previous is not None:
            return AuctionDecision(**previous.decision), {
                'provider': None, 'model': None,
                'prompt_version': AUCTION_PROMPT_VERSION,
                'reason': 'candidate_already_adjudicated',
                'reused_analysis_id': previous.pk,
                'candidate_key': candidate['key'],
                'analysis_cost': zero_analysis_cost('candidate_already_adjudicated'),
            }
        budget = ai_budget_status()
        if budget['exhausted']:
            return _fail_closed(snapshot, 'AI daily budget exhausted; fail closed.', {
                'reason': 'ai_daily_budget_exhausted',
                'ai_budget': budget,
                'analysis_cost': zero_analysis_cost('ai_daily_budget_exhausted'),
            })
        try:
            decision, runtime = AuctionAdjudicator().analyze(snapshot, candidate)
            return decision, {**runtime, 'candidate_key': candidate['key']}
        except AdjudicationError as exc:
            # The provider billed this response even though it was rejected.
            usage = dict(exc.usage)
            cost = usage.pop('analysis_cost', None) or unavailable_analysis_cost(
                'billed_response_without_pricing',
            )
            return _fail_closed(snapshot, 'AI response rejected by validation; fail closed.', {
                **usage,
                'candidate_key': candidate['key'],
                'error_type': type(exc.__cause__ or exc).__name__,
                'error_message': str(exc)[:500],
                'analysis_cost': {**cost, 'reason': 'billed_response_rejected'},
            })
        except Exception as exc:
            return _fail_closed(snapshot, 'AI adjudication failed; fail closed.', {
                'candidate_key': candidate['key'],
                'error_type': type(exc).__name__,
                'analysis_cost': unavailable_analysis_cost('api_error_without_usage'),
            })
    return AuctionDecision(**deterministic_preflight(snapshot)), {
        'provider': None, 'model': None,
        'prompt_version': AUCTION_PROMPT_VERSION,
        'reason': 'deterministic_only',
        'analysis_cost': zero_analysis_cost('deterministic_only'),
    }


def persist_analysis(snapshot: dict, decision: AuctionDecision, runtime: dict,
                     cycle_key: str | None = None) -> tuple[AuctionAnalysis, bool]:
    """Persist one immutable audit row; candidate ownership creates plans."""
    if cycle_key:
        existing = AuctionAnalysis.objects.filter(cycle_key=cycle_key).first()
        if existing is not None:
            return existing, False

    try:
        with transaction.atomic():
            analysis = AuctionAnalysis.objects.create(
                symbol=snapshot['symbol'],
                snapshot_hash=snapshot['snapshot_hash'],
                snapshot_version=snapshot['version'],
                prompt_version=runtime.get('prompt_version') or '',
                provider=runtime.get('provider') or '',
                model=runtime.get('model') or '',
                action=decision.action,
                direction=decision.direction,
                strategy_id=decision.strategy_id,
                snapshot=snapshot,
                decision=decision.model_dump(),
                runtime=runtime,
                shadow_only=True,
                cycle_key=cycle_key,
            )
    except IntegrityError:
        if cycle_key:
            return AuctionAnalysis.objects.get(cycle_key=cycle_key), False
        raise

    return analysis, True


def record_mechanical_baseline(snapshot: dict) -> dict:
    """Persist the control decision and one plan per candidate episode."""
    from .mechanical_baseline import BASELINE_VERSION, mechanical_decision

    cycle_key = analysis_cycle_key(snapshot, False, mode=BASELINE_VERSION)
    decision = mechanical_decision(snapshot)
    candidate = mechanical_candidate(snapshot) if decision.action == 'ARM' else None
    episode = _candidate_episode(candidate) if candidate else None
    runtime = {
        'provider': 'mechanical',
        'model': BASELINE_VERSION,
        'prompt_version': AUCTION_PROMPT_VERSION,
        'reason': 'mechanical_baseline',
        'analysis_cost': zero_analysis_cost('mechanical_baseline'),
    }
    if candidate and episode:
        runtime.update({'candidate_key': candidate['key'], 'candidate_id': episode.pk})
    analysis, created = persist_analysis(snapshot, decision, runtime, cycle_key)
    plan_created = _attach_baseline(episode, analysis) if episode else False
    trend_filter_result = (
        record_trend_filter(snapshot, decision, episode)
        if episode is not None and plan_created else None
    )
    global_context_result = (
        record_global_context_filter(snapshot, decision, episode)
        if episode is not None and plan_created else None
    )
    return {
        'analysis_id': analysis.pk,
        'created': created,
        'action': analysis.action,
        'direction': analysis.direction,
        'candidate_id': episode.pk if episode else None,
        'plan_created': plan_created,
        'trend_filter': trend_filter_result,
        'global_context_filter': global_context_result,
    }


def record_trend_filter(snapshot: dict, baseline_decision: AuctionDecision,
                        episode: AuctionCandidate) -> dict:
    """Persist prospective M1 once, on the birth snapshot of an M0 episode."""
    from .mechanical_baseline import TREND_FILTER_VERSION, trend_filtered_decision

    decision = trend_filtered_decision(snapshot, baseline_decision)
    cycle_key = analysis_cycle_key(snapshot, False, mode=TREND_FILTER_VERSION)
    runtime = {
        'provider': 'mechanical',
        'model': TREND_FILTER_VERSION,
        'prompt_version': AUCTION_PROMPT_VERSION,
        'reason': 'mechanical_trend_filter',
        'candidate_key': episode.fingerprint,
        'candidate_id': episode.pk,
        'analysis_cost': zero_analysis_cost('mechanical_trend_filter'),
    }
    analysis, created = persist_analysis(snapshot, decision, runtime, cycle_key)
    attached = _attach_trend_filter(episode, analysis)
    return {
        'analysis_id': analysis.pk,
        'created': created,
        'attached': attached,
        'action': analysis.action,
        'direction': analysis.direction,
        'version': TREND_FILTER_VERSION,
    }


def record_global_context_filter(snapshot: dict, baseline_decision: AuctionDecision,
                                 episode: AuctionCandidate) -> dict:
    """Persist prospective M3 once, on the birth snapshot of an M0 episode."""
    from .mechanical_baseline import (
        GLOBAL_CONTEXT_FILTER_VERSION,
        global_context_filter_assessment,
        global_context_filtered_decision,
    )

    assessment = global_context_filter_assessment(
        snapshot, baseline_decision.direction,
    )
    decision = global_context_filtered_decision(snapshot, baseline_decision)
    cycle_key = analysis_cycle_key(
        snapshot, False, mode=GLOBAL_CONTEXT_FILTER_VERSION,
    )
    runtime = {
        'provider': 'mechanical',
        'model': GLOBAL_CONTEXT_FILTER_VERSION,
        'prompt_version': AUCTION_PROMPT_VERSION,
        'reason': 'mechanical_global_context_filter',
        'policy_reason_code': assessment['reason_code'],
        'global_context_assessment': assessment,
        'candidate_key': episode.fingerprint,
        'candidate_id': episode.pk,
        'analysis_cost': zero_analysis_cost('mechanical_global_context_filter'),
    }
    analysis, created = persist_analysis(snapshot, decision, runtime, cycle_key)
    attached = _attach_global_context(episode, analysis)
    return {
        'analysis_id': analysis.pk,
        'created': created,
        'attached': attached,
        'action': analysis.action,
        'direction': analysis.direction,
        'version': GLOBAL_CONTEXT_FILTER_VERSION,
    }


def analyze_symbol(symbol: str, *, use_ai: bool, persist: bool = True,
                   deduplicate_bar: bool = False, baseline: bool = False) -> dict:
    snapshot = MarketSnapshotBuilder().build(symbol.upper())
    # The control arm runs on every bar, independent of AI dedup or budget.
    baseline_result = (
        record_mechanical_baseline(snapshot) if baseline and persist else None
    )
    cycle_key = analysis_cycle_key(snapshot, use_ai) if deduplicate_bar else None
    if cycle_key:
        existing = AuctionAnalysis.objects.filter(cycle_key=cycle_key).first()
        if existing is not None:
            # The original spend stays in ``runtime``; reusing it makes no new
            # API call, so this result must not be counted again.
            runtime = {**existing.runtime, 'deduplicated': True}
            return {
                'shadow_only': True,
                'execution_authorized': False,
                'snapshot': existing.snapshot,
                'decision': existing.decision,
                'runtime': runtime,
                'analysis_id': existing.pk,
                'created': False,
                'baseline': baseline_result,
                'analysis_cost': zero_analysis_cost('deduplicated_no_api_call'),
            }

    episode = None
    if baseline_result and baseline_result.get('candidate_id'):
        episode = AuctionCandidate.objects.select_related('ai_analysis').get(
            pk=baseline_result['candidate_id'],
        )
    decision, runtime = decide_snapshot(snapshot, use_ai, episode=episode)
    analysis = None
    created = False
    if persist:
        analysis, created = persist_analysis(snapshot, decision, runtime, cycle_key)
        if use_ai and runtime.get('candidate_key'):
            if episode is None:
                candidate = mechanical_candidate(snapshot)
                episode = _candidate_episode(candidate) if candidate else None
            if episode is not None:
                _attach_ai(episode, analysis)
    return {
        'shadow_only': True,
        'execution_authorized': False,
        'snapshot': snapshot,
        'decision': decision.model_dump(),
        'runtime': runtime,
        'analysis_id': analysis.pk if analysis else None,
        'created': created,
        'baseline': baseline_result,
        # Deliberately last: every human-facing analysis ends with its cost.
        'analysis_cost': runtime.get('analysis_cost') or unavailable_analysis_cost(
            'runtime_missing_cost',
        ),
    }
