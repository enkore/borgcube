from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='backupjob',
            name='repository',
        ),
        migrations.AddField(
            model_name='job',
            name='repository',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='jobs', to='core.Repository'),
        ),
    ]
