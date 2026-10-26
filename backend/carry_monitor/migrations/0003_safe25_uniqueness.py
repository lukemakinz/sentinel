from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('carry_monitor', '0002_safe25_paper_fields'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='carryepisode',
            constraint=models.UniqueConstraint(
                condition=models.Q(status='OPEN'),
                fields=('strategy',),
                name='one_open_carry_episode_per_strategy',
            ),
        ),
        migrations.AddConstraint(
            model_name='carrydecisionlog',
            constraint=models.UniqueConstraint(
                fields=('strategy', 'decision_time'),
                name='unique_carry_decision_per_strategy_month',
            ),
        ),
    ]
