from django.contrib import admin

from .models import CarryDecisionLog, CarryEpisode


@admin.register(CarryEpisode)
class CarryEpisodeAdmin(admin.ModelAdmin):
    list_display = [
        'strategy', 'symbol', 'status', 'opened_at', 'closed_at',
        'funding_accrued_usd', 'stress_pnl_usd',
        'min_futures_equity_usd', 'max_mark_leverage',
    ]
    list_filter = ['strategy', 'symbol', 'status']
    ordering = ['-opened_at']


@admin.register(CarryDecisionLog)
class CarryDecisionLogAdmin(admin.ModelAdmin):
    list_display = [
        'strategy', 'decision_time', 'previous_symbol',
        'target_symbol', 'reason',
    ]
    list_filter = ['strategy', 'reason']
    ordering = ['-decision_time']
