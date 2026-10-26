from django.contrib import admin
from .models import Position, Trade, AccountState, ExchangeOpenOrder, ExchangeFill, ExchangeClosedOrder

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


@admin.register(ExchangeOpenOrder)
class ExchangeOpenOrderAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'side', 'order_type', 'price', 'size', 'status', 'updated_at']
    list_filter = ['symbol', 'side', 'status']
    ordering = ['symbol', 'order_id']


@admin.register(ExchangeFill)
class ExchangeFillAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'side', 'price', 'size', 'pnl', 'liquidity', 'filled_at']
    list_filter = ['symbol', 'side', 'liquidity']
    ordering = ['-filled_at']


@admin.register(ExchangeClosedOrder)
class ExchangeClosedOrderAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'side', 'order_type', 'price', 'size', 'filled_size', 'status', 'closed_at']
    list_filter = ['symbol', 'side', 'status']
    ordering = ['-closed_at']
