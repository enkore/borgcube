from __future__ import unicode_literals

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_scheduleitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='scheduleitem',
            name='recurrence_start',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
