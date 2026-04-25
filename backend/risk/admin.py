from django.contrib import admin
from .models import RiskState, RiskEvent

@admin.register(RiskState)
class RiskStateAdmin(admin.ModelAdmin):
    list_display = ['daily_pnl', 'weekly_pnl', 'consecutive_losses', 'is_daily_stopped', 'is_weekly_stopped', 'position_size_multiplier']

@admin.register(RiskEvent)
class RiskEventAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'symbol', 'message', 'timestamp']
    list_filter = ['event_type']
    ordering = ['-timestamp']
