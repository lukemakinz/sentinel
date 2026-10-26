from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('executor', '0006_exchangefill'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExchangeClosedOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order_id', models.CharField(db_index=True, max_length=100, unique=True)),
                ('client_oid', models.CharField(blank=True, default='', max_length=100)),
                ('symbol', models.CharField(db_index=True, max_length=20)),
                ('side', models.CharField(choices=[('LONG', 'Long'), ('SHORT', 'Short')], max_length=5)),
                ('order_type', models.CharField(blank=True, default='', max_length=20)),
                ('price', models.FloatField(default=0)),
                ('size', models.FloatField(default=0)),
                ('filled_size', models.FloatField(default=0)),
                ('status', models.CharField(default='done', max_length=20)),
                ('cancel_reason', models.CharField(blank=True, default='', max_length=50)),
                ('source', models.CharField(default='exchange', max_length=20)),
                ('closed_at', models.DateTimeField(db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-closed_at', '-order_id'],
                'indexes': [models.Index(fields=['symbol', 'status', '-closed_at'], name='executor_ex_symbol_08859f_idx')],
            },
        ),
    ]
