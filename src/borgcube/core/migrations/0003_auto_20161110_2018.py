from __future__ import unicode_literals

from django.db import migrations
import jsonfield.fields


def move_data(apps, schema_editor):
    BackupJob = apps.get_model('core', 'BackupJob')
    for job in BackupJob.objects.all():
        job._data = job.data
        job.save()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_job_repository'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='_data',
            field=jsonfield.fields.JSONField(default=dict),
        ),
        migrations.RunPython(move_data),
        migrations.RemoveField(
            model_name='backupjob',
            name='data',
        ),
        migrations.RenameField(
            model_name='job',
            old_name='_data',
            new_name='data',
        )
    ]
