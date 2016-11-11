from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('core', '0005_backupjob_direct_config'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='_concrete_model',
            field=models.ForeignKey(default=14, on_delete=django.db.models.deletion.CASCADE, to='contenttypes.ContentType'),
            preserve_default=False,
        ),
    ]
