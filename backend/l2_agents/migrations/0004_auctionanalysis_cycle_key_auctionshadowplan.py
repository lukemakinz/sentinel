from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('l2_agents', '0003_auctionanalysis'),
    ]

    operations = [
        migrations.AddField(
            model_name='auctionanalysis',
            name='cycle_key',
            field=models.CharField(
                blank=True,
                help_text='Idempotency key for scheduled per-bar analysis cycles.',
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
        migrations.CreateModel(
            name='AuctionShadowPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbol', models.CharField(db_index=True, max_length=20)),
                ('strategy_id', models.CharField(db_index=True, max_length=64)),
                ('direction', models.CharField(max_length=5)),
                ('zone_kind', models.CharField(max_length=40)),
                ('zone_low', models.FloatField()),
                ('zone_high', models.FloatField()),
                ('structural_stop', models.FloatField()),
                ('target_r', models.FloatField(default=1.5)),
                ('management_policy', models.CharField(max_length=32)),
                ('armed_at', models.DateTimeField(db_index=True)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('state', models.CharField(choices=[('ARMED', 'Armed'), ('TRIGGERED', 'Triggered'), ('CLOSED', 'Closed'), ('EXPIRED', 'Expired'), ('INVALID', 'Invalid before entry')], db_index=True, default='ARMED', max_length=12)),
                ('triggered_at', models.DateTimeField(blank=True, null=True)),
                ('entry_price', models.FloatField(blank=True, null=True)),
                ('target_price', models.FloatField(blank=True, null=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('exit_price', models.FloatField(blank=True, null=True)),
                ('exit_reason', models.CharField(blank=True, choices=[('', 'Open'), ('TARGET', 'Target'), ('STOP', 'Stop'), ('TIME', 'Time expiry'), ('NO_TRIGGER', 'No trigger'), ('PRE_INVALIDATION', 'Invalidated before trigger')], max_length=20)),
                ('gross_r', models.FloatField(blank=True, null=True)),
                ('net_r', models.FloatField(blank=True, null=True)),
                ('mfe_r', models.FloatField(blank=True, null=True)),
                ('mae_r', models.FloatField(blank=True, null=True)),
                ('cost_assumptions', models.JSONField(default=dict)),
                ('trigger_evidence', models.JSONField(blank=True, default=dict)),
                ('analysis', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='shadow_plan', to='l2_agents.auctionanalysis')),
            ],
            options={
                'ordering': ['-armed_at'],
                'indexes': [
                    models.Index(fields=['state', 'expires_at'], name='l2_agents_a_state_1dc4da_idx'),
                    models.Index(fields=['symbol', '-armed_at'], name='l2_agents_a_symbol_b963eb_idx'),
                ],
            },
        ),
    ]
