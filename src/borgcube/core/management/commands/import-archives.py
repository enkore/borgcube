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
    help = _('Add existing archives to clients')

    def add_arguments(self, parser):
        # parser.add_argument('client', nargs='+', type=int)
        parser.add_argument('--regex', '-r', action='store_true')
        parser.add_argument('client')
        parser.add_argument('repository')
        parser.add_argument('archive')

    def handle(self, *args, **options):
        try:
            client = data_root().clients[options['client']]
        except KeyError:
            raise CommandError('Client %s not found' % options['client'])

        for repository in data_root().repositories:
            if repository.name == options['repository']:
                break
            if repository.id.startswith(options['repository']):
                break
            if repository.url == options['repository']:
                break
        else:
            raise CommandError('Repository %s not found' % options['repository'])

        with open_repository(repository) as borg_repository:
            manifest, key = Manifest.load(borg_repository)
            with Cache(borg_repository, key, manifest, lock_wait=1) as cache:
                names = self.find_archives(manifest, options['archive'], regex=options['regex'])
                imported = 0

                pi = ProgressIndicatorPercent(msg='Importing archives %4.1f %%: %s', total=len(names), step=0.1)
                for name in names:
                    imported += self.import_archive(manifest, cache, repository, name, client)
                    pi.show(info=[name])
                pi.finish()

        print('Imported %d archives.' % imported, file=sys.stderr)

    def find_archives(self, manifest, archive, regex):
        if regex:
            names = []
            for name in manifest.archives:
                if re.fullmatch(archive, name):
                    names.append(name)
            return names
        else:
            try:
                manifest.archives[archive]
                return [archive]
            except KeyError:
                raise CommandError('Archive %s not found' % archive)

    def import_archive(self, manifest, cache, repository, archive_name, client=None):
        with transaction.manager as txn:
            archive_info = manifest.archives[archive_name]

            fpr = bin_to_hex(archive_info.id)
            if fpr in data_root().archives:
                print('Skipping archive %s [%s], already known' % (archive_info.name, fpr), file=sys.stderr)
                return False

            archive = borg.archive.Archive(manifest.repository, manifest.key, manifest, archive_name, cache=cache)
            stats = archive.calc_stats(cache)
            duration = archive.ts_end - archive.ts

            Archive(
                id=archive.fpr,
                repository=repository,
                name=archive.name,
                client=client,
                nfiles=stats.nfiles,
                original_size=stats.osize,
                compressed_size=stats.csize,
                deduplicated_size=stats.usize,
                duration=duration,
                timestamp=archive.ts,
                timestamp_end=archive.ts_end,
            )
            txn.note('(cli) associated archive %s on repository %s with client %s' % (
                archive_name, repository.name, client.hostname
            ))
            return True
