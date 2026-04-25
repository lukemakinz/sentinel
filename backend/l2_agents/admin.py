from django.contrib import admin
from .models import L2Decision


@admin.register(L2Decision)
class L2DecisionAdmin(admin.ModelAdmin):
    list_display  = ['symbol', 'timestamp', 'direction', 'action', 'size_multiplier', 'veto_reason']
    list_filter   = ['symbol', 'action', 'direction']
    ordering      = ['-timestamp']
    readonly_fields = ['timestamp', 'agents_summary', 'trade_context']
