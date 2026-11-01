"""Conservative evidence report for prospective Auction Intelligence plans."""
import json
import math

from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Sum

from l2_agents.auction_adjudicator import (
    summarize_analysis_costs,
    unavailable_analysis_cost,
)
from l2_agents.auction_learning import summarize_postmortems
from l2_agents.auction_service import ai_budget_status
from l2_agents.models import AuctionAnalysis, AuctionCandidate, AuctionShadowPlan


def _safe(value, digits=4):
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _track_summary(plans) -> dict:
    closed = plans.filter(state='CLOSED', net_r__isnull=False)
    count = closed.count()
    gross_profit = closed.filter(net_r__gt=0).aggregate(value=Sum('net_r'))['value'] or 0.0
    gross_loss = closed.filter(net_r__lte=0).aggregate(value=Sum('net_r'))['value'] or 0.0
    return {
        'plans': plans.count(),
        'closed': count,
        'win_rate': _safe(closed.filter(net_r__gt=0).count() / count) if count else None,
        'expectancy_net_r': _safe(closed.aggregate(value=Avg('net_r'))['value']),
        'total_net_r': _safe(closed.aggregate(value=Sum('net_r'))['value']),
        'profit_factor': _safe(gross_profit / abs(gross_loss)) if gross_loss < 0 else None,
    }


TERMINAL_STATES = ('CLOSED', 'EXPIRED', 'INVALID')


def _outcome_r(plan) -> float:
    return float(plan.net_r) if plan.state == 'CLOSED' and plan.net_r is not None else 0.0


def _policy_summary(rows: list, selected) -> dict:
    """Score one policy on every completely resolved candidate, including 0R."""
    chosen = [plan for plan in rows if selected(plan)]
    filled = [
        plan for plan in chosen
        if plan.state == 'CLOSED' and plan.net_r is not None
    ]
    wins = sum(float(plan.net_r) > 0 for plan in filled)
    gross_profit = sum(max(float(plan.net_r), 0.0) for plan in filled)
    gross_loss = sum(min(float(plan.net_r), 0.0) for plan in filled)
    total = sum(_outcome_r(plan) for plan in chosen)
    common_filled = sum(
        plan.state == 'CLOSED' and plan.net_r is not None for plan in rows
    )
    return {
        'plans': len(chosen),
        'closed': len(filled),
        'selected_candidates': len(chosen),
        'comparison_candidates': len(rows),
        'policy_candidates': len(rows),
        # Backward-compatible field: number of filled outcomes in the common
        # cohort. New clients should use comparison_candidates for the 0R-aware
        # denominator.
        'policy_closed_candidates': common_filled,
        'policy_resolved_candidates': len(rows),
        'rejected_candidates': len(rows) - len(chosen),
        'win_rate': _safe(wins / len(filled)) if filled else None,
        'expectancy_net_r': _safe(
            sum(float(plan.net_r) for plan in filled) / len(filled),
        ) if filled else None,
        'total_net_r': _safe(total),
        'profit_factor': _safe(gross_profit / abs(gross_loss))
        if gross_loss < 0 else None,
        'policy_expectancy_per_candidate_r': _safe(total / len(rows))
        if rows else None,
    }


def _paired_policy_summary() -> dict:
    """Score M0, M1 and M2 on the same resolved candidate episodes."""
    paired = AuctionShadowPlan.objects.filter(
        analysis__baseline_candidate__ai_analysis__isnull=False,
        analysis__baseline_candidate__trend_filter_analysis__isnull=False,
    ).select_related(
        'analysis__baseline_candidate__trend_filter_analysis',
        'analysis__baseline_candidate__ai_analysis',
    )
    rows = list(paired.filter(state__in=TERMINAL_STATES))
    baseline = _policy_summary(rows, lambda _plan: True)
    trend = _policy_summary(
        rows,
        lambda plan: plan.analysis.baseline_candidate.trend_filter_analysis.action == 'ARM',
    )
    ai = _policy_summary(
        rows,
        lambda plan: plan.analysis.baseline_candidate.ai_analysis.action == 'ARM',
    )
    baseline_total = baseline['total_net_r'] or 0.0
    trend_total = trend['total_net_r'] or 0.0
    ai_total = ai['total_net_r'] or 0.0
    denominator = len(rows)
    paired_filled = sum(
        plan.state == 'CLOSED' and plan.net_r is not None for plan in rows
    )
    trend_uplift = ai_uplift = ai_vs_trend = None
    if denominator:
        trend_uplift = _safe((trend_total - baseline_total) / denominator)
        ai_uplift = _safe((ai_total - baseline_total) / denominator)
        ai_vs_trend = _safe((ai_total - trend_total) / denominator)
    return {
        'candidate_episodes': AuctionCandidate.objects.count(),
        'adjudicated_candidates': paired.count(),
        'paired_closed_candidates': paired_filled,
        'paired_resolved_candidates': denominator,
        'm0_mechanical_baseline': baseline,
        'm1_trend_filter': trend,
        'm2_ai': ai,
        'm1_uplift_vs_m0_per_candidate_r': trend_uplift,
        'm2_uplift_vs_m0_per_candidate_r': ai_uplift,
        'm2_uplift_vs_m1_per_candidate_r': ai_vs_trend,
        # Backwards-compatible aliases for the Telegram report and old clients.
        'ai': ai,
        'mechanical_baseline': baseline,
        'ai_uplift_per_candidate_r': ai_uplift,
    }


def _global_context_policy_summary() -> dict:
    """Score M0 and M3 on one prospective cohort without requiring an AI call."""
    cohort = AuctionShadowPlan.objects.filter(
        analysis__baseline_candidate__global_context_analysis__isnull=False,
    ).select_related('analysis__baseline_candidate__global_context_analysis')
    rows = list(cohort.filter(state__in=TERMINAL_STATES))

    def analysis(plan):
        return plan.analysis.baseline_candidate.global_context_analysis

    baseline = _policy_summary(rows, lambda _plan: True)
    global_policy = _policy_summary(rows, lambda plan: analysis(plan).action == 'ARM')
    denominator = len(rows)
    paired_filled = sum(
        plan.state == 'CLOSED' and plan.net_r is not None for plan in rows
    )
    baseline_total = baseline['total_net_r'] or 0.0
    global_total = global_policy['total_net_r'] or 0.0
    reason_counts: dict[str, int] = {}
    eligible_rows = []
    for plan in rows:
        reason = (analysis(plan).runtime or {}).get(
            'policy_reason_code', 'LEGACY_UNCLASSIFIED',
        )
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if reason != 'DATA_INELIGIBLE':
            eligible_rows.append(plan)
    eligible_baseline = _policy_summary(eligible_rows, lambda _plan: True)
    eligible_global = _policy_summary(
        eligible_rows, lambda plan: analysis(plan).action == 'ARM',
    )
    eligible_uplift = None
    if eligible_rows:
        eligible_uplift = _safe(
            ((eligible_global['total_net_r'] or 0.0)
             - (eligible_baseline['total_net_r'] or 0.0)) / len(eligible_rows)
        )
    return {
        'candidate_episodes': cohort.count(),
        'paired_closed_candidates': paired_filled,
        'paired_resolved_candidates': denominator,
        'm0_mechanical_baseline': baseline,
        'm3_global_context': global_policy,
        'reason_codes': dict(sorted(reason_counts.items())),
        'm3_uplift_vs_m0_per_candidate_r': (
            _safe((global_total - baseline_total) / denominator)
            if denominator else None
        ),
        'context_eligible_only': {
            'candidates': len(eligible_rows),
            'm0_mechanical_baseline': eligible_baseline,
            'm3_global_context': eligible_global,
            'm3_uplift_vs_m0_per_candidate_r': eligible_uplift,
        },
        'guardrail': (
            'Prospective shadow comparison only; external TOTAL/dominance '
            'indicators are not used by global-context-v1.3-fresh-breadth20. '
            'DATA_INELIGIBLE is reported separately from a context veto.'
        ),
    }


def _latest_global_context(symbol: str | None = None) -> dict | None:
    rows = AuctionAnalysis.objects.order_by('-timestamp')
    if symbol:
        rows = rows.filter(symbol=symbol.upper())
    for row in rows.only('symbol', 'timestamp', 'snapshot')[:250]:
        snapshot = row.snapshot or {}
        context = snapshot.get('global_context')
        if context:
            return {
                'symbol': row.symbol,
                'snapshot_timestamp': row.timestamp.isoformat(),
                'snapshot_as_of': snapshot.get('as_of'),
                **context,
            }
    return None


def build_report(symbol: str | None = None) -> dict:
    analyses = AuctionAnalysis.objects.all()
    plans = AuctionShadowPlan.objects.all()
    closed = plans.filter(state='CLOSED', net_r__isnull=False)
    wins = closed.filter(net_r__gt=0)
    losses = closed.filter(net_r__lte=0)
    gross_profit = wins.aggregate(value=Sum('net_r'))['value'] or 0.0
    gross_loss = losses.aggregate(value=Sum('net_r'))['value'] or 0.0
    closed_count = closed.count()
    paired_comparison = _paired_policy_summary()
    paired_closed_count = paired_comparison['paired_closed_candidates']
    global_context_comparison = _global_context_policy_summary()
    global_closed_count = global_context_comparison['paired_closed_candidates']

    grouped = []
    for row in closed.values('strategy_id', 'direction').annotate(
        trades=Count('id'), expectancy=Avg('net_r'), total_net_r=Sum('net_r'),
    ).order_by('strategy_id', 'direction'):
        grouped.append({
            **row,
            'expectancy': _safe(row['expectancy']),
            'total_net_r': _safe(row['total_net_r']),
        })

    return {
        'shadow_only': True,
        'execution_authorized': False,
        'analyses': {
            'total': analyses.count(),
            'PASS': analyses.filter(action='PASS').count(),
            'WAIT': analyses.filter(action='WAIT').count(),
            'ARM': analyses.filter(action='ARM').count(),
        },
        'plans': {
            'total': plans.count(),
            'ARMED': plans.filter(state='ARMED').count(),
            'TRIGGERED': plans.filter(state='TRIGGERED').count(),
            'CLOSED': closed_count,
            'EXPIRED': plans.filter(state='EXPIRED').count(),
            'INVALID': plans.filter(state='INVALID').count(),
        },
        'performance': {
            'win_rate': _safe(wins.count() / closed_count) if closed_count else None,
            'expectancy_net_r': _safe(closed.aggregate(value=Avg('net_r'))['value']),
            'total_net_r': _safe(closed.aggregate(value=Sum('net_r'))['value']),
            'profit_factor': _safe(gross_profit / abs(gross_loss)) if gross_loss < 0 else None,
            'target_exits': closed.filter(exit_reason='TARGET').count(),
            'stop_exits': closed.filter(exit_reason='STOP').count(),
            'time_exits': closed.filter(exit_reason='TIME').count(),
        },
        'by_strategy_direction': grouped,
        'candidate_cohort': _track_summary(plans.filter(
            analysis__baseline_candidate__isnull=False,
        )),
        'learning_postmortems': summarize_postmortems(plans),
        # One M0 outcome per candidate; M1/M2/M3 PASS or WAIT scores 0R.
        'paired_comparison': paired_comparison,
        'global_context_comparison': global_context_comparison,
        'latest_global_context': _latest_global_context(symbol),
        'evidence_gate': {
            'minimum_closed_plans': 100,
            'sample_ready': paired_closed_count >= 100,
            'promotion_allowed': False,
            'global_context': {
                'minimum_filled_plans': 100,
                'filled_plans': global_closed_count,
                'sample_ready': global_closed_count >= 100,
                'promotion_allowed': False,
            },
            'reason': (
                'Research sample reached; walk-forward and paired baseline tests still required.'
                if paired_closed_count >= 100
                else f'Need at least {100 - paired_closed_count} more paired closed candidates before inference.'
            ),
        },
        'ai_budget': ai_budget_status(),
        # Deliberately last in the human-facing report.
        'analysis_cost': summarize_analysis_costs(
            (analysis.runtime or {}).get('analysis_cost')
            or unavailable_analysis_cost('legacy_record_without_cost')
            for analysis in analyses.only('runtime')
        ),
    }


class Command(BaseCommand):
    help = 'Report prospective net-R evidence for auction-shadow plans.'

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(build_report(), indent=2))
