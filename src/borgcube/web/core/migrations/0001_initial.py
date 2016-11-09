from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='OverviewMetric',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('py_class', models.CharField(max_length=100)),
                ('label', models.CharField(max_length=100)),
                ('order', models.IntegerField(default=0)),
            ],
            options={'ordering': ['order']},
        ),
    ]
