from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('executor', '0005_exchangeopenorder'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExchangeFill',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trade_id', models.CharField(db_index=True, max_length=100, unique=True)),
                ('order_id', models.CharField(blank=True, db_index=True, default='', max_length=100)),
                ('symbol', models.CharField(db_index=True, max_length=20)),
                ('side', models.CharField(choices=[('LONG', 'Long'), ('SHORT', 'Short')], max_length=5)),
                ('price', models.FloatField(default=0)),
                ('size', models.FloatField(default=0)),
                ('value', models.FloatField(default=0)),
                ('fee', models.FloatField(default=0)),
                ('pnl', models.FloatField(default=0)),
                ('liquidity', models.CharField(blank=True, default='', max_length=20)),
                ('source', models.CharField(default='exchange', max_length=20)),
                ('filled_at', models.DateTimeField(db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-filled_at', '-trade_id'],
                'indexes': [models.Index(fields=['symbol', '-filled_at'], name='executor_ex_symbol_b1deec_idx')],
            },
        ),
    ]
