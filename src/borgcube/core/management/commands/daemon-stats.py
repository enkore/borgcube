
from datetime import timedelta

from django.core.management import BaseCommand
from django.utils.translation import ugettext as _

from borgcube.daemon.client import APIClient
from borgcube.web.core.templatetags.borgcube import format_timedelta


class Command(BaseCommand):
    help = _('Show daemon statistics')

    def handle(self, *args, **options):
        stats = APIClient().stats()
        maxlen = len(max(stats, key=len))

        for name, value in stats.items():
            if name == 'uptime':
                value = format_timedelta(timedelta(seconds=value))
            print(name.ljust(maxlen).replace('_', ' '), value)
