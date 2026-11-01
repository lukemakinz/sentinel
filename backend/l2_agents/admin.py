from django.contrib import admin
from .models import AuctionAnalysis, AuctionCandidate, AuctionShadowPlan, L2Decision


@admin.register(L2Decision)
class L2DecisionAdmin(admin.ModelAdmin):
    list_display  = ['symbol', 'timestamp', 'direction', 'action', 'size_multiplier', 'veto_reason']
    list_filter   = ['symbol', 'action', 'direction']
    ordering      = ['-timestamp']
    readonly_fields = ['timestamp', 'agents_summary', 'trade_context']


@admin.register(AuctionAnalysis)
class AuctionAnalysisAdmin(admin.ModelAdmin):
    list_display = [
        'symbol', 'timestamp', 'action', 'direction', 'strategy_id', 'shadow_only',
    ]
    list_filter = ['symbol', 'action', 'direction', 'strategy_id', 'shadow_only']
    ordering = ['-timestamp']
    readonly_fields = ['timestamp', 'snapshot', 'decision', 'runtime']


@admin.register(AuctionShadowPlan)
class AuctionShadowPlanAdmin(admin.ModelAdmin):
    list_display = [
        'symbol', 'armed_at', 'strategy_id', 'direction', 'state',
        'exit_reason', 'net_r',
    ]
    list_filter = ['symbol', 'strategy_id', 'direction', 'state', 'exit_reason']
    ordering = ['-armed_at']
    readonly_fields = [
        'analysis', 'armed_at', 'triggered_at', 'closed_at',
        'cost_assumptions', 'trigger_evidence', 'postmortem_version',
        'postmortem', 'postmortem_at',
    ]


@admin.register(AuctionCandidate)
class AuctionCandidateAdmin(admin.ModelAdmin):
    list_display = [
        'symbol', 'first_seen_at', 'strategy_id', 'direction',
        'baseline_analysis', 'trend_filter_analysis',
        'global_context_analysis', 'ai_analysis',
    ]
    list_filter = ['symbol', 'strategy_id', 'direction']
    ordering = ['-first_seen_at']
    readonly_fields = [
        'fingerprint', 'active_fingerprint', 'first_seen_at',
        'adjudication_expires_at', 'baseline_analysis',
        'trend_filter_analysis', 'global_context_analysis', 'ai_analysis',
    ]
