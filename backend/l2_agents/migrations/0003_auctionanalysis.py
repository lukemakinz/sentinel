from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('l2_agents', '0002_l2decision_dismissed_l2decision_trade_params'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuctionAnalysis',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbol', models.CharField(db_index=True, max_length=20)),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('snapshot_hash', models.CharField(db_index=True, max_length=64)),
                ('snapshot_version', models.CharField(max_length=64)),
                ('prompt_version', models.CharField(blank=True, max_length=64)),
                ('provider', models.CharField(blank=True, max_length=30)),
                ('model', models.CharField(blank=True, max_length=80)),
                ('action', models.CharField(choices=[('PASS', 'Pass'), ('WAIT', 'Wait'), ('ARM', 'Arm')], max_length=10)),
                ('direction', models.CharField(default='NONE', max_length=5)),
                ('strategy_id', models.CharField(default='NONE', max_length=64)),
                ('snapshot', models.JSONField(default=dict)),
                ('decision', models.JSONField(default=dict)),
                ('runtime', models.JSONField(default=dict)),
                ('shadow_only', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['-timestamp'],
                'indexes': [models.Index(fields=['symbol', '-timestamp'], name='l2_agents_a_symbol_7bb5a2_idx')],
            },
        ),
    ]
