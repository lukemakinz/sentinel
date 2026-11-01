"""Deterministic post-mortems and execution counterfactuals for shadow plans.

This module diagnoses observations; it never changes a strategy, selects a new
parameter, or authorizes execution.  Every result is versioned so future rules
cannot silently rewrite the historical research record.
"""
from __future__ import annotations

from datetime import timedelta
from statistics import mean

from django.db import transaction
from django.utils import timezone


POSTMORTEM_VERSION = 'auction-postmortem-v3-intraday-management'
LIMIT_ENTRY_TTL_MINUTES = 5
TARGET_VARIANTS_R = (1.0, 1.5, 2.0)
TERMINAL_STATES = ('CLOSED', 'EXPIRED', 'INVALID')


def _adverse_fill(price: float, direction: str, slippage_bps: float) -> float:
    slip = float(slippage_bps) / 10_000.0
    return price * (1.0 - slip if direction == 'LONG' else 1.0 + slip)


def _score(*, direction: str, entry: float, stop: float, raw_exit: float,
           exit_reason: str, entry_fee_bps: float, exit_fee_bps: float,
           slippage_bps: float) -> dict:
    exit_price = (
        raw_exit if exit_reason == 'TARGET'
        else _adverse_fill(raw_exit, direction, slippage_bps)
    )
    risk = abs(entry - stop)
    gross = (
        (exit_price - entry) / risk
        if direction == 'LONG' else (entry - exit_price) / risk
    )
    fee_r = (
        entry * float(entry_fee_bps) / 10_000.0
        + exit_price * float(exit_fee_bps) / 10_000.0
    ) / risk
    return {
        'exit_reason': exit_reason,
        'entry_price': round(entry, 8),
        'exit_price': round(exit_price, 8),
        'gross_r': round(gross, 6),
        'fee_r': round(fee_r, 6),
        'net_r': round(gross - fee_r, 6),
    }


def _simulate(*, plan, rows: list[dict], entry: float, target_r: float,
              entry_fee_bps: float, start_index: int = 0) -> dict:
    costs = plan.cost_assumptions or {}
    stop = float(plan.structural_stop)
    risk = abs(entry - stop)
    if risk <= 0:
        return {'complete': False, 'reason': 'invalid_geometry'}
    target = (
        entry + risk * target_r
        if plan.direction == 'LONG' else entry - risk * target_r
    )
    mfe = mae = 0.0
    active_rows = rows[start_index:]
    for row in active_rows:
        high, low = float(row['high']), float(row['low'])
        if plan.direction == 'LONG':
            favorable = (high - entry) / risk
            adverse = (low - entry) / risk
            stop_touched = low <= stop
            target_touched = high >= target
        else:
            favorable = (entry - low) / risk
            adverse = (entry - high) / risk
            stop_touched = high >= stop
            target_touched = low <= target
        mfe, mae = max(mfe, favorable), min(mae, adverse)
        # Intrabar ordering is unknown, so every counterfactual uses the same
        # conservative stop-first convention as the canonical resolver.
        if stop_touched:
            result = _score(
                direction=plan.direction, entry=entry, stop=stop,
                raw_exit=stop, exit_reason='STOP',
                entry_fee_bps=entry_fee_bps,
                exit_fee_bps=float(costs['stop_taker_fee_bps']),
                slippage_bps=float(costs['market_slippage_bps']),
            )
            return {**result, 'complete': True, 'mfe_r': round(mfe, 6),
                    'mae_r': round(mae, 6), 'target_r': target_r}
        if target_touched:
            result = _score(
                direction=plan.direction, entry=entry, stop=stop,
                raw_exit=target, exit_reason='TARGET',
                entry_fee_bps=entry_fee_bps,
                exit_fee_bps=float(costs['target_maker_fee_bps']),
                slippage_bps=0.0,
            )
            return {**result, 'complete': True, 'mfe_r': round(mfe, 6),
                    'mae_r': round(mae, 6), 'target_r': target_r}

    if not active_rows:
        return {'complete': False, 'reason': 'no_post_entry_rows'}
    last = active_rows[-1]
    result = _score(
        direction=plan.direction, entry=entry, stop=stop,
        raw_exit=float(last['close']), exit_reason='TIME',
        entry_fee_bps=entry_fee_bps,
        exit_fee_bps=float(costs['stop_taker_fee_bps']),
        slippage_bps=float(costs['market_slippage_bps']),
    )
    return {**result, 'complete': True, 'mfe_r': round(mfe, 6),
            'mae_r': round(mae, 6), 'target_r': target_r}


def _limit_counterfactual(plan, rows: list[dict]) -> dict:
    """Post-confirmation maker limit at the trigger close, valid five minutes."""
    evidence = (plan.trigger_evidence or {}).get('candle') or {}
    try:
        limit_price = float(evidence['close'])
    except (KeyError, TypeError, ValueError):
        return {'complete': False, 'reason': 'missing_trigger_close'}

    fill_deadline = plan.triggered_at + timedelta(minutes=LIMIT_ENTRY_TTL_MINUTES)
    fill_index = None
    for index, row in enumerate(rows):
        if row['timestamp'] > fill_deadline:
            break
        touched = (
            float(row['low']) <= limit_price
            if plan.direction == 'LONG' else float(row['high']) >= limit_price
        )
        if touched:
            fill_index = index
            break
    if fill_index is None:
        return {
            'complete': True,
            'filled': False,
            'exit_reason': 'NO_FILL',
            'gross_r': 0.0,
            'net_r': 0.0,
            'entry_ttl_minutes': LIMIT_ENTRY_TTL_MINUTES,
        }

    result = _simulate(
        plan=plan, rows=rows, entry=limit_price,
        target_r=float(plan.target_r),
        entry_fee_bps=float((plan.cost_assumptions or {})['target_maker_fee_bps']),
        start_index=fill_index,
    )
    return {
        **result,
        'filled': bool(result.get('complete')),
        'fill_timestamp': rows[fill_index]['timestamp'].isoformat(),
        'entry_ttl_minutes': LIMIT_ENTRY_TTL_MINUTES,
    }


def _trend_context(plan) -> dict:
    state = (plan.analysis.snapshot or {}).get('trend_state') or {}
    return {
        'version': state.get('version'),
        'regime': state.get('regime', 'UNKNOWN'),
        'directional_bias': state.get('directional_bias', 'NEUTRAL'),
        'alignment': state.get('alignment', 'UNKNOWN'),
        'alignment_score': state.get('alignment_score_minus100_100'),
        'timeframes': {
            interval: {
                'direction': value.get('direction', 'UNKNOWN'),
                'strength_0_100': value.get('strength_0_100', 0.0),
            }
            for interval, value in (state.get('timeframes') or {}).items()
        },
    }


def _global_context(plan) -> dict:
    from .global_context import candidate_alignment

    context = (plan.analysis.snapshot or {}).get('global_context') or {}
    alignment = candidate_alignment(context, plan.direction)
    return {
        'version': context.get('version'),
        'state': context.get('state', 'UNKNOWN'),
        'target_class': context.get('target_class'),
        'target_bias_score_minus100_100': context.get(
            'target_bias_score_minus100_100',
        ),
        'target_data_coverage_0_1': context.get('target_data_coverage_0_1', 0.0),
        'candidate_alignment': alignment,
        'external_data_used': bool(context.get('external_data_used')),
        'attribution_guardrail': (
            'Alignment is contemporaneous evidence, not proof that global '
            'context caused the outcome.'
        ),
    }


def _policy_actions(plan) -> dict:
    result = {
        'm0': 'ARM', 'm1': 'UNAVAILABLE',
        'm2': 'UNAVAILABLE', 'm3': 'UNAVAILABLE',
    }
    try:
        candidate = plan.analysis.baseline_candidate
    except Exception:
        return result
    if candidate.trend_filter_analysis_id:
        result['m1'] = candidate.trend_filter_analysis.action
    if candidate.ai_analysis_id:
        result['m2'] = candidate.ai_analysis.action
    if candidate.global_context_analysis_id:
        result['m3'] = candidate.global_context_analysis.action
    return result


def _context_tags(tags: list[str], actual: dict, global_context: dict) -> list[str]:
    """Add non-causal context labels to a completed post-mortem."""
    if actual.get('state') != 'CLOSED' or actual.get('net_r') is None:
        return tags
    alignment = (global_context.get('candidate_alignment') or {}).get('status')
    net_r = float(actual['net_r'])
    if alignment == 'OPPOSED':
        label = 'global_headwind_present' if net_r <= 0 else 'global_headwind_overcome'
        return [*tags, label]
    if alignment == 'ALIGNED':
        label = 'global_tailwind_failed' if net_r <= 0 else 'global_tailwind_present'
        return [*tags, label]
    return tags


def _diagnose(plan, actual: dict, targets: dict, limit: dict,
              management: dict | None = None) -> tuple[str, list[str], str]:
    if plan.state == 'EXPIRED':
        return 'NO_TRIGGER', ['candidate_never_confirmed'], 'Setup expired without a valid trigger.'
    if plan.state == 'INVALID':
        return 'PRE_INVALIDATION', ['structure_failed_before_entry'], 'Structure failed before entry; no trade was taken.'
    if not actual.get('coverage_complete'):
        return 'DATA_INCOMPLETE', ['counterfactuals_unavailable'], 'Candle coverage was insufficient for a reliable post-mortem.'

    net = float(actual.get('net_r') or 0.0)
    gross = float(actual.get('gross_r') or 0.0)
    mfe = float(actual.get('mfe_r') or 0.0)
    tags = [f"exit_{str(plan.exit_reason).lower()}"]
    if plan.exit_reason == 'TARGET' and net > 0:
        return 'SUCCESS', tags, 'The frozen target was reached after costs.'
    if plan.exit_reason == 'STOP' and mfe >= float(plan.target_r):
        return 'PATH_AMBIGUITY', [*tags, 'stop_and_target_possible'], 'One-minute data cannot order the stop and target; conservative stop-first scoring applies.'
    if gross > 0 >= net:
        return 'COST_DRAG', [*tags, 'gross_positive_net_nonpositive'], 'Gross edge was positive but fees and slippage removed it.'
    if limit.get('complete') and float(limit.get('net_r') or 0.0) >= net + 0.5:
        return 'ENTRY_QUALITY', [*tags, 'limit_improved_by_0_5r'], 'The frozen post-confirmation limit counterfactual improved the result by at least 0.5R.'
    management = management or {}
    alternatives = [
        value for value in [*targets.values(), *management.values()]
        if value.get('complete')
    ]
    best_alternative = max(
        (float(value.get('net_r') or 0.0) for value in alternatives),
        default=net,
    )
    if best_alternative >= net + 0.5 and mfe >= 0.5:
        return (
            'MANAGEMENT_GIVEBACK',
            [*tags, 'frozen_management_improved_by_0_5r'],
            'Price moved favorably and a preregistered exit policy improved '
            'the result by at least 0.5R on the same candles.',
        )
    if mfe < 0.5:
        return 'SIGNAL_FAILURE', [*tags, 'mfe_below_0_5r'], 'The setup never produced 0.5R favorable excursion.'
    return 'NO_FOLLOW_THROUGH', [*tags, 'mfe_at_least_0_5r'], 'The setup moved favorably but did not sustain enough follow-through.'


def build_postmortem(plan, now=None) -> dict | None:
    """Build a post-mortem, or return None until the observation window closes."""
    from ingester.models import Candle

    now = now or timezone.now()
    if plan.state not in TERMINAL_STATES:
        return None

    global_context = _global_context(plan)
    base = {
        'version': POSTMORTEM_VERSION,
        'research_only': True,
        'execution_authorized': False,
        'plan_id': plan.pk,
        'symbol': plan.symbol,
        'strategy_id': plan.strategy_id,
        'direction': plan.direction,
        'policy_actions': _policy_actions(plan),
        'trend_at_candidate': _trend_context(plan),
        'global_context_at_candidate': global_context,
        'guardrail': 'Diagnostic only; never auto-select a policy or mutate strategy parameters.',
    }
    if plan.state in {'EXPIRED', 'INVALID'}:
        actual = {'coverage_complete': True, 'state': plan.state, 'net_r': 0.0}
        diagnosis, tags, explanation = _diagnose(plan, actual, {}, {})
        tags = _context_tags(tags, actual, global_context)
        return {
            **base,
            'primary_diagnosis': diagnosis,
            'diagnosis_tags': tags,
            'explanation': explanation,
            'actual': actual,
            'counterfactuals': {},
        }

    deadline = plan.position_expires_at
    if not deadline and plan.triggered_at:
        deadline = plan.triggered_at + timedelta(minutes=int(
            (plan.cost_assumptions or {}).get('max_hold_minutes') or 240,
        ))
    if not plan.triggered_at or not deadline:
        return {
            **base,
            'primary_diagnosis': 'DATA_INCOMPLETE',
            'diagnosis_tags': ['missing_trigger_or_deadline'],
            'explanation': 'Closed plan lacks a replayable trigger or holding deadline.',
            'actual': {'coverage_complete': False},
            'counterfactuals': {},
        }
    if now < deadline:
        return None

    rows = list(Candle.objects.filter(
        symbol=plan.symbol, interval='1m', is_closed=True,
        timestamp__gt=plan.triggered_at, timestamp__lt=deadline,
    ).order_by('timestamp').values('timestamp', 'open', 'high', 'low', 'close'))
    coverage_complete = bool(
        rows and rows[-1]['timestamp'] >= deadline - timedelta(minutes=2)
    )
    if not coverage_complete:
        # Give late data time to arrive, then close the learning record without
        # inventing counterfactual outcomes.
        if now < deadline + timedelta(hours=12):
            return None
        actual = {
            'coverage_complete': False,
            'state': plan.state,
            'exit_reason': plan.exit_reason,
            'net_r': plan.net_r,
            'gross_r': plan.gross_r,
            'mfe_r': plan.mfe_r,
            'mae_r': plan.mae_r,
        }
        diagnosis, tags, explanation = _diagnose(plan, actual, {}, {})
        tags = _context_tags(tags, actual, global_context)
        return {
            **base,
            'primary_diagnosis': diagnosis,
            'diagnosis_tags': tags,
            'explanation': explanation,
            'actual': actual,
            'counterfactuals': {},
        }

    target_results = {
        f'market_target_{target_r:.1f}r': _simulate(
            plan=plan, rows=rows, entry=float(plan.entry_price),
            target_r=target_r,
            entry_fee_bps=float((plan.cost_assumptions or {})['entry_taker_fee_bps']),
        )
        for target_r in TARGET_VARIANTS_R
    }
    from .intraday_management import POLICY_IDS, simulate_intraday_policy

    management_results = {
        f'intraday_{policy_id.lower()}': simulate_intraday_policy(
            direction=plan.direction,
            entry=float(plan.entry_price),
            initial_stop=float(plan.structural_stop),
            rows=rows,
            costs=plan.cost_assumptions or {},
            policy_id=policy_id,
            opened_at=plan.triggered_at,
        )
        for policy_id in POLICY_IDS
    }
    limit_result = _limit_counterfactual(plan, rows)
    actual = {
        'coverage_complete': True,
        'state': plan.state,
        'exit_reason': plan.exit_reason,
        'entry_price': plan.entry_price,
        'exit_price': plan.exit_price,
        'gross_r': plan.gross_r,
        'net_r': plan.net_r,
        'cost_drag_r': round(float(plan.gross_r or 0.0) - float(plan.net_r or 0.0), 6),
        'mfe_r': plan.mfe_r,
        'mae_r': plan.mae_r,
    }
    diagnosis, tags, explanation = _diagnose(
        plan, actual, target_results, limit_result, management_results,
    )
    tags = _context_tags(tags, actual, global_context)
    return {
        **base,
        'primary_diagnosis': diagnosis,
        'diagnosis_tags': tags,
        'explanation': explanation,
        'actual': actual,
        'counterfactuals': {
            **target_results,
            **management_results,
            'post_confirmation_limit_5m': limit_result,
        },
    }


def ensure_postmortem(plan, now=None) -> str:
    """Persist one immutable diagnosis, safely idempotent across schedulers."""
    if plan.postmortem_version:
        return 'EXISTS'
    now = now or timezone.now()
    payload = build_postmortem(plan, now=now)
    if payload is None:
        return 'PENDING'
    with transaction.atomic():
        locked = type(plan).objects.select_for_update().get(pk=plan.pk)
        if locked.postmortem_version:
            return 'EXISTS'
        locked.postmortem_version = POSTMORTEM_VERSION
        locked.postmortem = payload
        locked.postmortem_at = now
        locked.save(update_fields=['postmortem_version', 'postmortem', 'postmortem_at'])
    return 'CREATED'


def summarize_postmortems(plans) -> dict:
    """Aggregate immutable learning records without optimizing a parameter."""
    records = [plan.postmortem for plan in plans if plan.postmortem_version]
    diagnoses: dict[str, int] = {}
    regime_values: dict[str, list[float]] = {}
    global_state_values: dict[str, list[float]] = {}
    global_alignment_values: dict[str, list[float]] = {}
    actual_values, candidate_values, cost_drag_values, limit_values = [], [], [], []
    limit_fills = 0
    target_values: dict[str, list[float]] = {
        f'market_target_{value:.1f}r': [] for value in TARGET_VARIANTS_R
    }
    from .intraday_management import POLICY_IDS

    management_values: dict[str, list[float]] = {
        f'intraday_{policy_id.lower()}': [] for policy_id in POLICY_IDS
    }
    management_tp1_hits = {key: 0 for key in management_values}
    for record in records:
        diagnosis = record.get('primary_diagnosis', 'UNKNOWN')
        diagnoses[diagnosis] = diagnoses.get(diagnosis, 0) + 1
        actual = record.get('actual') or {}
        if actual.get('coverage_complete') and actual.get('net_r') is not None:
            actual_net = float(actual['net_r'])
            candidate_values.append(actual_net)
            if actual.get('state') == 'CLOSED':
                actual_values.append(actual_net)
                if actual.get('cost_drag_r') is not None:
                    cost_drag_values.append(float(actual['cost_drag_r']))
                regime = (record.get('trend_at_candidate') or {}).get('regime', 'UNKNOWN')
                regime_values.setdefault(regime, []).append(actual_net)
                global_context = record.get('global_context_at_candidate') or {}
                global_state = global_context.get('state', 'UNKNOWN')
                global_alignment = (
                    global_context.get('candidate_alignment') or {}
                ).get('status', 'UNKNOWN')
                global_state_values.setdefault(global_state, []).append(actual_net)
                global_alignment_values.setdefault(global_alignment, []).append(actual_net)
        counterfactuals = record.get('counterfactuals') or {}
        for key in target_values:
            value = counterfactuals.get(key) or {}
            if value.get('complete') and value.get('net_r') is not None:
                target_values[key].append(float(value['net_r']))
        for key in management_values:
            value = counterfactuals.get(key) or {}
            if value.get('complete') and value.get('net_r') is not None:
                management_values[key].append(float(value['net_r']))
                management_tp1_hits[key] += int(bool(value.get('tp1_hit')))
        limit = counterfactuals.get('post_confirmation_limit_5m') or {}
        if limit.get('complete'):
            limit_values.append(float(limit.get('net_r') or 0.0))
            limit_fills += int(bool(limit.get('filled')))

    def average(values):
        return round(mean(values), 6) if values else None

    return {
        'version': POSTMORTEM_VERSION,
        'records': len(records),
        'filled_records': len(actual_values),
        'diagnoses': dict(sorted(diagnoses.items())),
        'actual_mean_net_r': average(actual_values),
        'candidate_mean_net_r_including_no_trade': average(candidate_values),
        'mean_cost_drag_r': average(cost_drag_values),
        'counterfactual_mean_net_r': {
            **{key: average(values) for key, values in target_values.items()},
            **{key: average(values) for key, values in management_values.items()},
            'post_confirmation_limit_5m': average(limit_values),
        },
        'counterfactual_tp1_hit_rate': {
            key: (
                round(management_tp1_hits[key] / len(values), 4)
                if values else None
            )
            for key, values in management_values.items()
        },
        'post_confirmation_limit_fill_rate': (
            round(limit_fills / len(limit_values), 4) if limit_values else None
        ),
        'by_entry_trend_regime': {
            key: {'records': len(values), 'mean_actual_net_r': average(values)}
            for key, values in sorted(regime_values.items())
        },
        'by_entry_global_state': {
            key: {'records': len(values), 'mean_actual_net_r': average(values)}
            for key, values in sorted(global_state_values.items())
        },
        'by_global_alignment': {
            key: {'records': len(values), 'mean_actual_net_r': average(values)}
            for key, values in sorted(global_alignment_values.items())
        },
        'guardrail': 'Descriptive evidence only; no automatic parameter or strategy changes.',
    }
