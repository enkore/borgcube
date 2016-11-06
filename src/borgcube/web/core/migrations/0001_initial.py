from __future__ import unicode_literals

from django.db import migrations, models

from ..metrics import ArchiveCount, TotalData, BackupsToday


def configure_default_metrics(apps, schema_editor):
    OverviewMetric = apps.get_model('web_core', 'OverviewMetric')
    OverviewMetric(py_class='borgcube.web.core.metrics.ArchiveCount', label=ArchiveCount.default_label, order=0).save()
    OverviewMetric(py_class='borgcube.web.core.metrics.TotalData', label=TotalData.default_label, order=1).save()
    OverviewMetric(py_class='borgcube.web.core.metrics.BackupsToday', label=BackupsToday.default_label, order=2).save()


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
        migrations.RunPython(configure_default_metrics),
    ]
