"""Conservative evidence report for prospective Auction Intelligence plans."""
import json
import math

from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Sum

from l2_agents.auction_adjudicator import (
    summarize_analysis_costs,
    unavailable_analysis_cost,
)
from l2_agents.auction_service import ai_budget_status
from l2_agents.models import AuctionAnalysis, AuctionShadowPlan


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


def build_report() -> dict:
    analyses = AuctionAnalysis.objects.all()
    plans = AuctionShadowPlan.objects.all()
    closed = plans.filter(state='CLOSED', net_r__isnull=False)
    wins = closed.filter(net_r__gt=0)
    losses = closed.filter(net_r__lte=0)
    gross_profit = wins.aggregate(value=Sum('net_r'))['value'] or 0.0
    gross_loss = losses.aggregate(value=Sum('net_r'))['value'] or 0.0
    closed_count = closed.count()

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
        # AI must beat the frozen no-AI rule on the same bars to justify itself.
        'paired_comparison': {
            'ai': _track_summary(plans.filter(
                analysis__provider__in=['openai', 'anthropic'],
            )),
            'mechanical_baseline': _track_summary(plans.filter(
                analysis__provider='mechanical',
            )),
        },
        'evidence_gate': {
            'minimum_closed_plans': 100,
            'sample_ready': closed_count >= 100,
            'promotion_allowed': False,
            'reason': (
                'Research sample reached; walk-forward and paired baseline tests still required.'
                if closed_count >= 100
                else f'Need at least {100 - closed_count} more closed plans before inference.'
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
