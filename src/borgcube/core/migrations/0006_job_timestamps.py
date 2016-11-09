from __future__ import unicode_literals

from django.db import migrations, models
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_archive_duration'),
    ]

    operations = [
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
