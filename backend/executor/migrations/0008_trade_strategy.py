from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('executor', '0007_exchangeclosedorder'),
    ]

    operations = [
        migrations.AddField(
            model_name='trade',
            name='strategy',
            field=models.CharField(db_index=True, default='S1', max_length=5),
        ),
    ]
