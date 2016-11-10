
import logging

from django.db.models import Sum
from django.utils.translation import pgettext_lazy as _
from django.utils import timezone

from borg.helpers import format_file_size

from borgcube.core.models import Archive, BackupJob

from .models import OverviewMetric
from .metrics import Metric

log = logging.getLogger(__name__)


def borgcube_startup():
    if not OverviewMetric.objects.all().count():
        # Just add ourselves
        log.info(ArchiveCount.__qualname__)
        default_metrics = ArchiveCount, TotalData, BackupsToday
        OverviewMetric.objects.bulk_create(
            OverviewMetric(py_class=__name__ + '.' + cls.__name__, label=cls.default_label, order=n)
            for n, cls in enumerate(default_metrics)
        )
        log.info('added default built-in metrics (ArchiveCount, TotalData, BackupsToday)')


def borgcube_web_metrics():
    return (
        ArchiveCount,
        TotalData,
        BackupsToday,
    )


class ArchiveCount(Metric):
    name = _('ArchiveCount metric name', 'Number of archives')
    default_label = _('ArchiveCount metric label', 'archives')

    def formatted_value(self):
        return str(Archive.objects.count())


class TotalData(Metric):
    name = _('TotalData metric name', 'Total amount of data in repositories')
    default_label = _('TotalData metric label', '(total data)')

    def formatted_value(self):
        return format_file_size(Archive.objects.all().aggregate(Sum('original_size'))['original_size__sum'] or 0)


class BackupsToday(Metric):
    name = _('BackupsToday metric name', 'Backups made today')
    default_label = _('BackupsToday metric label', 'backups today')

    def formatted_value(self):
        today_begin = timezone.now().replace(hour=0, minute=0, microsecond=0)
        return str(BackupJob.objects.filter(timestamp_end__gte=today_begin, state=BackupJob.State.done).count())
