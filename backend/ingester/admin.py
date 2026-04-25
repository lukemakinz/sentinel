from django.contrib import admin
from .models import (
    Candle, FundingRate, Liquidation, OpenInterest,
    LongShortRatio, TopTraderPosition, MarketTicker,
    AggTrade, WhaleThreshold, WhaleCVD, RetailCVD,
)


@admin.register(Candle)
class CandleAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'interval', 'timestamp', 'open', 'high', 'low', 'close', 'volume']
    list_filter = ['symbol', 'interval']
    ordering = ['-timestamp']


@admin.register(FundingRate)
class FundingRateAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'timestamp', 'funding_rate', 'mark_price']
    list_filter = ['symbol']
    ordering = ['-timestamp']


@admin.register(Liquidation)
class LiquidationAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'timestamp', 'side', 'price', 'quantity', 'usd_value']
    list_filter = ['symbol', 'side']
    ordering = ['-timestamp']


@admin.register(OpenInterest)
class OpenInterestAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'timestamp', 'open_interest', 'open_interest_value']
    list_filter = ['symbol']
    ordering = ['-timestamp']


@admin.register(LongShortRatio)
class LongShortRatioAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'timestamp', 'long_short_ratio', 'long_account', 'short_account']
    list_filter = ['symbol']
    ordering = ['-timestamp']


@admin.register(TopTraderPosition)
class TopTraderPositionAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'timestamp', 'long_short_ratio', 'long_account', 'short_account']
    list_filter = ['symbol']
    ordering = ['-timestamp']


@admin.register(MarketTicker)
class MarketTickerAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'timestamp', 'price', 'price_change_pct', 'volume_24h']
    list_filter = ['symbol']
    ordering = ['-timestamp']


@admin.register(AggTrade)
class AggTradeAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'timestamp', 'price', 'quantity', 'usd_value', 'is_buyer_maker']
    list_filter = ['symbol', 'is_buyer_maker']
    ordering = ['-timestamp']


@admin.register(WhaleThreshold)
class WhaleThresholdAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'timestamp', 'threshold_usd']
    list_filter = ['symbol']
    ordering = ['-timestamp']


@admin.register(WhaleCVD)
class WhaleCVDAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'timestamp', 'cumulative_delta']
    list_filter = ['symbol']
    ordering = ['-timestamp']


@admin.register(RetailCVD)
class RetailCVDAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'timestamp', 'cumulative_delta']
    list_filter = ['symbol']
    ordering = ['-timestamp']
