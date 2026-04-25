from django.contrib import admin
from .models import ConsensusSignal


@admin.register(ConsensusSignal)
class ConsensusSignalAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'conviction_score', 'bias', 'tier', 'agreeing_analysts', 'timestamp']
    list_filter = ['symbol', 'tier', 'bias']
    ordering = ['-timestamp']
