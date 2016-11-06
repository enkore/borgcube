from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='repository',
            name='manifest_id',
            field=models.CharField(default='0000000000000000000000000000000000000000000000000000000000000000', max_length=200),
        ),
        migrations.AlterField(
            model_name='job',
            name='client',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='jobs', to='core.Client'),
        ),
    ]
