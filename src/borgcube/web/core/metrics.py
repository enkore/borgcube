from datetime import datetime

from django.db.models import Sum
from django.utils.translation import pgettext_lazy as _

from borg.helpers import format_file_size

from borgcube.core.models import Archive, Job


class Metric:
    name = None
    default_label = None

    def formatted_value(self):
        pass


class ArchiveCount(Metric):
    name = _('ArchiveCount metric name', 'Number of archives')
    default_label = _('ArchiveCount metric label', 'archives')

    def formatted_value(self):
        return str(Archive.objects.count())


class TotalData(Metric):
    name = _('TotalData metric name', 'Total amount of data in repositories')
    default_label = _('TotalData metric label', '(total data)')

    def formatted_value(self):
        return format_file_size(Archive.objects.all().aggregate(Sum('original_size'))['original_size__sum'])


class BackupsToday(Metric):
    name = _('BackupsToday metric name', 'Backups made today')
    default_label = _('BackupsToday metric label', 'backups today')

    def formatted_value(self):
        today_begin = datetime.now().replace(hour=0, minute=0, microsecond=0)
        return str(Job.objects.filter(timestamp__gte=today_begin, db_state=Job.State.done.value).count())
