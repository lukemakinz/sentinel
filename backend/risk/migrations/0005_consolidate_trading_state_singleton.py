from django.db import migrations


SEVERITY = {
    'NORMAL': 0,
    'CAUTION': 1,
    'DEFENSIVE': 2,
    'CLOSE_ONLY': 3,
    'HALT': 4,
}


def consolidate(apps, schema_editor):
    TradingState = apps.get_model('risk', 'TradingState')
    rows = list(TradingState.objects.all())
    if not rows:
        TradingState.objects.create(pk=1)
        return
    chosen = max(
        rows,
        key=lambda row: (
            SEVERITY.get(row.state, 0), bool(row.manual_unlock), row.since,
        ),
    )
    singleton, _ = TradingState.objects.get_or_create(pk=1)
    singleton.state = chosen.state
    singleton.reason = chosen.reason
    singleton.manual_unlock = chosen.manual_unlock
    singleton.set_by = chosen.set_by
    singleton.since = chosen.since
    singleton.save()
    TradingState.objects.exclude(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [('risk', '0004_tradingstate_alter_riskevent_event_type')]
    operations = [migrations.RunPython(consolidate, migrations.RunPython.noop)]
