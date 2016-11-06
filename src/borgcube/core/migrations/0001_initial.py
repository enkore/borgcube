from __future__ import unicode_literals

import borgcube.core.models
from django.db import migrations, models
import django.db.models.deletion
import jsonfield.fields
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Archive',
            fields=[
                ('id', models.CharField(max_length=200, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('comment', models.TextField(blank=True)),
                ('nfiles', models.BigIntegerField()),
                ('original_size', models.BigIntegerField()),
                ('compressed_size', models.BigIntegerField()),
                ('deduplicated_size', models.BigIntegerField()),
            ],
        ),
        migrations.CreateModel(
            name='Client',
            fields=[
                ('hostname', borgcube.core.models.SlugWithDotField(help_text='Only letters and numbers (A-Z, 0-9), dashes, underscores and dots (._-).', max_length=200, primary_key=True, serialize=False, verbose_name='Hostname')),
                ('name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
            ],
        ),
        migrations.CreateModel(
            name='ClientConnection',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('remote', models.CharField(help_text='Usually something like root@somehost, but you can also give a .ssh/config host alias, for example.', max_length=200)),
                ('rsh', models.CharField(default='ssh', max_length=200, verbose_name='RSH')),
                ('rsh_options', models.CharField(blank=True, default=None, max_length=200, null=True, verbose_name='RSH options')),
                ('ssh_identity_file', models.CharField(blank=True, default=None, max_length=200, null=True, verbose_name='SSH identity file')),
                ('remote_borg', models.CharField(default='borg', max_length=200, verbose_name='Remote borg binary name')),
                ('remote_cache_dir', models.CharField(blank=True, default=None, help_text='If not specified the Borg default will be used (usually ~/.cache/borg/).', max_length=200, null=True, verbose_name='Remote cache directory')),
            ],
        ),
        migrations.CreateModel(
            name='Job',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('data', jsonfield.fields.JSONField(default=dict)),
                ('state', models.CharField(choices=[('job-created', 'job_created'), ('client-preparing', 'client_preparing'), ('client-prepared', 'client_prepared'), ('client-in-progress', 'client_in_progress'), ('client-done', 'client_done'), ('client-cleanup', 'client_cleanup'), ('cache_sync', 'cache_sync'), ('done', 'done'), ('failed', 'failed')], default='job-created', max_length=200)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.Client')),
            ],
            options={
                'ordering': ['-timestamp'],
            },
        ),
        migrations.CreateModel(
            name='JobConfig',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('config', jsonfield.fields.TypedJSONField(default={'version': 1})),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='job_configs', to='core.Client')),
            ],
        ),
        migrations.CreateModel(
            name='Repository',
            fields=[
                ('id', models.CharField(help_text='32 bytes in hex', max_length=200, primary_key=True, serialize=False, verbose_name='Repository ID')),
                ('name', models.CharField(max_length=200)),
                ('url', models.CharField(help_text='For example /data0/reposity or user@storage:/path.', max_length=1000)),
            ],
        ),
        migrations.AddField(
            model_name='jobconfig',
            name='repository',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='job_configs', to='core.Repository'),
        ),
        migrations.AddField(
            model_name='job',
            name='config',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.JobConfig'),
        ),
        migrations.AddField(
            model_name='job',
            name='repository',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.Repository'),
        ),
        migrations.AddField(
            model_name='client',
            name='connection',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='core.ClientConnection'),
        ),
        migrations.AddField(
            model_name='archive',
            name='job',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.Job'),
        ),
        migrations.AddField(
            model_name='archive',
            name='repository',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.Repository'),
        ),
    ]
