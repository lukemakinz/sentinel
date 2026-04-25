from django.contrib import admin
from .models import L1Result


@admin.register(L1Result)
class L1ResultAdmin(admin.ModelAdmin):
    list_display  = ['symbol', 'timestamp', 'direction', 'passed', 'gates_b_count', 'gates_c_count']
    list_filter   = ['symbol', 'direction', 'passed']
    ordering      = ['-timestamp']
    readonly_fields = ['timestamp', 'gates_a', 'gates_b', 'gates_c', 'trade_context']
