from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_auto_20161112_0024'),
    ]

    operations = [
        migrations.AddField(
            model_name='checkconfig',
            name='label',
            field=models.CharField(default='', max_length=200),
            preserve_default=False,
        ),
    ]
