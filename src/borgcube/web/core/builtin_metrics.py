
import logging

import transaction

from django.utils.translation import pgettext_lazy as _, ugettext_lazy
from django.utils import timezone

from borg.helpers import format_file_size

from borgcube.core.models import Job, NumberTree
from borgcube.utils import data_root

from .metrics import Metric
from . import views

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
        today_begin = timezone.now().replace(hour=0, minute=0, microsecond=0)
        jobs = 0
        for job in NumberTree.reversed(data_root().jobs_by_state[Job.State.done]):
            if job.created < today_begin:
                break
            jobs += 1
        transaction.abort()
        return str(jobs)


def borgcube_web_management_nav(nav):
    nav.append({
        'view': views.prune,
        'text': ugettext_lazy('Pruning'),
        'items': [
            {
                'view': views.prune_retention_policies,
                'text': ugettext_lazy('Retention policies'),
            },
            {
                'view': views.prune_configs,
                'text': ugettext_lazy('Configurations'),
            }
        ],
    })
