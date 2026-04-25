from django.contrib import admin
from .models import AnalystSignalRecord


@admin.register(AnalystSignalRecord)
class AnalystSignalRecordAdmin(admin.ModelAdmin):
    list_display = ['analyst_name', 'symbol', 'score', 'bias', 'confidence', 'timestamp']
    list_filter = ['analyst_name', 'symbol', 'bias']
    ordering = ['-timestamp']
    readonly_fields = ['metadata']
