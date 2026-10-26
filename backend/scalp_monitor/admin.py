from django.contrib import admin

from .models import ScalpDecisionLog, ScalpPaperTrade


@admin.register(ScalpPaperTrade)
class ScalpPaperTradeAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'side', 'status', 'opened_at', 'closed_at',
                    'entry_price', 'exit_price', 'realized_pnl_usd', 'r_multiple']
    list_filter = ['symbol', 'side', 'status', 'exit_reason']
    ordering = ['-opened_at']


@admin.register(ScalpDecisionLog)
class ScalpDecisionLogAdmin(admin.ModelAdmin):
    list_display = ['checked_at', 'symbol', 'action']
    list_filter = ['action', 'symbol']
    ordering = ['-checked_at']
