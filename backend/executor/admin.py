from django.contrib import admin
from .models import Position, Trade, AccountState

@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'side', 'status', 'entry_price', 'current_price', 'unrealized_pnl', 'tier', 'opened_at']
    list_filter = ['status', 'symbol', 'side', 'tier']
    ordering = ['-opened_at']

@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'side', 'entry_price', 'exit_price', 'pnl', 'pnl_percent', 'risk_reward', 'close_reason', 'exit_time']
    list_filter = ['symbol', 'side', 'close_reason']
    ordering = ['-exit_time']

@admin.register(AccountState)
class AccountStateAdmin(admin.ModelAdmin):
    list_display = ['balance', 'equity', 'unrealized_pnl', 'total_trades', 'winning_trades', 'max_drawdown', 'updated_at']
    ordering = ['-updated_at']
