from __future__ import unicode_literals

from django.db import migrations
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_auto_20161110_2156'),
    ]

    operations = [
        migrations.AlterField(
            model_name='backupjob',
            name='config',
            field=jsonfield.fields.JSONField(default=dict),
        ),
    ]
