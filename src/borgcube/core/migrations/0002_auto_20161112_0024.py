from __future__ import unicode_literals

from django.db import migrations
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='checkjob',
            name='config',
            field=jsonfield.fields.JSONField(default=dict),
        ),
    ]
