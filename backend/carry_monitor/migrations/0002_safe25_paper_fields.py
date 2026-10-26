from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('carry_monitor', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='carrydecisionlog',
            name='features',
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name='carrydecisionlog',
            name='protocol_sha256',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='carrydecisionlog',
            name='strategy',
            field=models.CharField(db_index=True, default='S11_LEGACY', max_length=30),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='adverse_funding_usd',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='futures_margin_usd',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='last_safety_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='max_mark_leverage',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='min_futures_equity_usd',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='protocol_sha256',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='reserve_usd',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='severe_costs_usd',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='severe_pnl_usd',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='strategy',
            field=models.CharField(db_index=True, default='S11_LEGACY', max_length=30),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='stress_costs_usd',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='carryepisode',
            name='stress_pnl_usd',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
