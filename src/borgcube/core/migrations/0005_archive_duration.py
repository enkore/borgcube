from __future__ import unicode_literals

import datetime

from django.db import migrations, models



class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_repository_remote'),
    ]

    operations = [
        migrations.AddField(
            model_name='archive',
            name='duration',
            field=models.DurationField(default=datetime.timedelta()),
            preserve_default=False,
        ),
    ]
