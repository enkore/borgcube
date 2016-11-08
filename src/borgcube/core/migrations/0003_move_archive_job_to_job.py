from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_job_state_rename'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='archive',
            name='job',
        ),
        migrations.AddField(
            model_name='job',
            name='archive',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.Archive'),
        ),
    ]
