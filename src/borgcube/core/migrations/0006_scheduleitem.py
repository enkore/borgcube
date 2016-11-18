from __future__ import unicode_literals

from django.db import migrations, models
import jsonfield.fields
import recurrence.fields


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_delete_scheduleitem'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScheduleItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('py_class', models.CharField(max_length=100)),
                ('py_args', jsonfield.fields.JSONField(default=dict)),
                ('name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('recurrence', recurrence.fields.RecurrenceField()),
            ],
        ),
    ]
