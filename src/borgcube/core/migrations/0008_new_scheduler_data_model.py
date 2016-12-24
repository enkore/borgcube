from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_scheduleitem_recurrence_start'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScheduledAction',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('py_class', models.CharField(max_length=100)),
                ('py_args', jsonfield.fields.JSONField(default=dict)),
                ('order', models.IntegerField()),
            ],
            options={
                'ordering': ['order'],
            },
        ),
        migrations.RemoveField(
            model_name='scheduleitem',
            name='py_args',
        ),
        migrations.RemoveField(
            model_name='scheduleitem',
            name='py_class',
        ),
        migrations.AddField(
            model_name='scheduledaction',
            name='item',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='actions', to='core.ScheduleItem'),
        ),
    ]
