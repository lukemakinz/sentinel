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
from .models import AuctionAnalysis


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


def decide_snapshot(snapshot: dict, use_ai: bool) -> tuple[AuctionDecision, dict]:
    """Adjudicate one already-built immutable snapshot and always fail closed."""
    if use_ai:
        budget = ai_budget_status()
        if budget['exhausted']:
            return _fail_closed(snapshot, 'AI daily budget exhausted; fail closed.', {
                'reason': 'ai_daily_budget_exhausted',
                'ai_budget': budget,
                'analysis_cost': zero_analysis_cost('ai_daily_budget_exhausted'),
            })
        try:
            return AuctionAdjudicator().analyze(snapshot)
        except AdjudicationError as exc:
            # The provider billed this response even though it was rejected.
            usage = dict(exc.usage)
            cost = usage.pop('analysis_cost', None) or unavailable_analysis_cost(
                'billed_response_without_pricing',
            )
            return _fail_closed(snapshot, 'AI response rejected by validation; fail closed.', {
                **usage,
                'error_type': type(exc.__cause__ or exc).__name__,
                'error_message': str(exc)[:500],
                'analysis_cost': {**cost, 'reason': 'billed_response_rejected'},
            })
        except Exception as exc:
            return _fail_closed(snapshot, 'AI adjudication failed; fail closed.', {
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
    """Persist an audit row and materialize replayable geometry for ``ARM``."""
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
            if decision.action == 'ARM':
                from .shadow_auction import create_shadow_plan
                create_shadow_plan(analysis)
    except IntegrityError:
        if cycle_key:
            return AuctionAnalysis.objects.get(cycle_key=cycle_key), False
        raise

    return analysis, True


def record_mechanical_baseline(snapshot: dict) -> dict:
    """Persist the no-AI control decision for this bar (once per bar)."""
    from .mechanical_baseline import BASELINE_VERSION, mechanical_decision

    cycle_key = analysis_cycle_key(snapshot, False, mode=BASELINE_VERSION)
    decision = mechanical_decision(snapshot)
    analysis, created = persist_analysis(snapshot, decision, {
        'provider': 'mechanical',
        'model': BASELINE_VERSION,
        'prompt_version': AUCTION_PROMPT_VERSION,
        'reason': 'mechanical_baseline',
        'analysis_cost': zero_analysis_cost('mechanical_baseline'),
    }, cycle_key)
    return {
        'analysis_id': analysis.pk,
        'created': created,
        'action': analysis.action,
        'direction': analysis.direction,
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

    decision, runtime = decide_snapshot(snapshot, use_ai)
    analysis = None
    created = False
    if persist:
        analysis, created = persist_analysis(snapshot, decision, runtime, cycle_key)
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
