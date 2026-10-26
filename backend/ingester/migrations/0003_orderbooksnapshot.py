from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ingester', '0002_watchedpair'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrderBookSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbol', models.CharField(db_index=True, max_length=20)),
                ('timestamp', models.DateTimeField(db_index=True)),
                ('last_update_id', models.BigIntegerField(default=0)),
                ('bids', models.JSONField(default=list)),
                ('asks', models.JSONField(default=list)),
                ('best_bid', models.DecimalField(decimal_places=8, max_digits=20)),
                ('best_ask', models.DecimalField(decimal_places=8, max_digits=20)),
                ('mid_price', models.DecimalField(decimal_places=8, max_digits=20)),
                ('spread_bps', models.DecimalField(decimal_places=4, max_digits=12)),
                ('bid_depth_5_usd', models.DecimalField(decimal_places=2, default=0, max_digits=30)),
                ('ask_depth_5_usd', models.DecimalField(decimal_places=2, default=0, max_digits=30)),
                ('bid_depth_20_usd', models.DecimalField(decimal_places=2, default=0, max_digits=30)),
                ('ask_depth_20_usd', models.DecimalField(decimal_places=2, default=0, max_digits=30)),
                ('imbalance_5', models.DecimalField(decimal_places=6, default=0, max_digits=10)),
                ('imbalance_20', models.DecimalField(decimal_places=6, default=0, max_digits=10)),
            ],
            options={
                'ordering': ['-timestamp'],
                'indexes': [models.Index(fields=['symbol', '-timestamp'], name='ingester_or_symbol_75bf5a_idx')],
            },
        ),
    ]
