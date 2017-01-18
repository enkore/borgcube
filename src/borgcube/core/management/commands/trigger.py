import re
import sys

import transaction

import borg.archive
from borg.cache import Cache
from borg.helpers import Manifest, ProgressIndicatorPercent, bin_to_hex

from django.core.management import BaseCommand
from django.core.management import CommandError
from django.utils.translation import ugettext as _

from borgcube.utils import data_root, open_repository
from borgcube.core.models import Archive


class Command(BaseCommand):
    help = _('Trigger action by id.')

    def add_arguments(self, parser):
        parser.add_argument('trigger-id', dest='trigger_id')

    def handle(self, *args, **options):
        try:
            trig = data_root().trigger_ids[options['trigger_id']]
        except KeyError:
            raise CommandError('Trigger %s not found' % options['trigger_id'])
        trig.run(access_context='local')
