from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_move_archive_job_to_job'),
    ]

    operations = [
        migrations.AddField(
            model_name='repository',
            name='remote_borg',
            field=models.CharField(default='borg', max_length=200, verbose_name='Remote borg binary name (only applies to remote repositories)'),
        ),
        migrations.AlterField(
            model_name='job',
            name='db_state',
            field=models.CharField(choices=[('job-created', 'job_created'), ('client-preparing', 'client_preparing'), ('client-prepared', 'client_prepared'), ('client-in-progress', 'client_in_progress'), ('client-done', 'client_done'), ('client-cleanup', 'client_cleanup'), ('done', 'done'), ('failed', 'failed')], default='job-created', max_length=200),
        ),
    ]
