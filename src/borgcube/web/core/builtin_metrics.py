
import logging

from django.utils.translation import pgettext_lazy as _
from django.utils import timezone

from borg.helpers import format_file_size

from borgcube.core.models import BackupJob
from borgcube.utils import data_root

from .metrics import Metric

log = logging.getLogger(__name__)


class ArchiveCount(Metric):
    name = _('ArchiveCount metric name', 'Number of archives')
    label = _('ArchiveCount metric label', 'archives')

    def formatted_value(self):
        return str(len(data_root().archives))


class TotalData(Metric):
    name = _('TotalData metric name', 'Total amount of data in repositories')
    label = _('TotalData metric label', '(total data)')

    def formatted_value(self):
        total_size = 0
        for archive in data_root().archives.values():
            total_size += archive.original_size
        return format_file_size(total_size)


class BackupsToday(Metric):
    name = _('BackupsToday metric name', 'Backups made today')
    label = _('BackupsToday metric label', 'backups today')

    def formatted_value(self):
        today_begin = int(timezone.now().replace(hour=0, minute=0, microsecond=0).timestamp())
        return str(len(list(data_root().jobs_by_state[BackupJob.State.done].keys(min=today_begin))))
