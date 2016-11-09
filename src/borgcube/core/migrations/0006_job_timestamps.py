from __future__ import unicode_literals

from django.db import migrations, models
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_archive_duration'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScheduleItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('py_class', models.CharField(max_length=100)),
                ('py_args', jsonfield.fields.JSONField(default=dict)),
                ('name', models.CharField(max_length=200)),
            ],
        ),
        migrations.AlterModelOptions(
            name='job',
            options={'ordering': ['-created']},
        ),
        migrations.RenameField(
            model_name='job',
            old_name='timestamp',
            new_name='created',
        ),
        migrations.AddField(
            model_name='job',
            name='timestamp_end',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='job',
            name='timestamp_start',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
