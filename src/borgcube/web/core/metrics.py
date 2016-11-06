from django.utils.translation import pgettext_lazy as _


class Metric:
    name = None
    default_label = None

    def formatted_value(self):
        pass


class ArchiveCount(Metric):
    name = _('ArchiveCount metric name', 'Number of archives')
    default_label = _('ArchiveCount metric label', 'archives')

    def formatted_value(self):
        return '451'


class TotalData(Metric):
    name = _('TotalData metric name', 'Total amount of data in repositories')
    default_label = _('TotalData metric label', '(total data)')

    def formatted_value(self):
        return '44.7 TB'


class BackupsToday(Metric):
    name = _('BackupsToday metric name', 'Backups made today')
    default_label = _('BackupsToday metric label', 'backups today')

    def formatted_value(self):
        return '9'
