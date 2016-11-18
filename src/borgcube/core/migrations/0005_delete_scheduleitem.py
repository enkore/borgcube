from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_job_no_uuid'),
    ]

    operations = [
        migrations.DeleteModel(
            name='ScheduleItem',
        ),
    ]
