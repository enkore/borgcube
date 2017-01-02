import logging
import re
from itertools import groupby
from functools import partial

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

from persistent.list import PersistentList

from borg.archive import Statistics
from borg.cache import Cache
from borg.helpers import prune_split, Manifest

from borgcube.core.models import Evolvable, JobExecutor, Job, s
from borgcube.utils import data_root, validate_regex, open_repository

KeepField = partial(forms.IntegerField, min_value=-1, initial=-1)

log = logging.getLogger(__name__)


class PruneRoot(Evolvable):
    def __init__(self):
        self.policies = PersistentList()
        self.configs = PersistentList()


def prune_root():
    return data_root().plugin_data('prune', PruneRoot)


class RetentionPolicy(Evolvable):
    def __init__(self, name, description='',
                 keep_secondly=-1, keep_minutely=-1, keep_hourly=-1,
                 keep_daily=-1, keep_weekly=-1, keep_monthly=-1, keep_yearly=-1):
        self.name = name
        self.description = description
        self.keep_secondly = keep_secondly
        self.keep_minutely = keep_minutely
        self.keep_hourly = keep_hourly
        self.keep_daily = keep_daily
        self.keep_weekly = keep_weekly
        self.keep_monthly = keep_monthly
        self.keep_yearly = keep_yearly

    def __str__(self):
        return self.name

    def apply(self, archives):
        """
        Apply this policy to a list of `Archives <Archive>`.

        Return a list of two-tuples (should_delete, archive), where *should_delete* means that the archive
        should be deleted according to this policy.
        """
        # This is more or less adapted from borg.archiver.Archiver.do_prune; it's buried in there and not
        # really accessible otherwise.

        # Note: archives does not contain checkpoints, which simplifies this quite a bit.

        keep = set()
        if self.keep_secondly:
            keep.update(prune_split(archives, '%Y-%m-%d %H:%M:%S', self.keep_secondly, keep))
        if self.keep_minutely:
            keep.update(prune_split(archives, '%Y-%m-%d %H:%M', self.keep_minutely, keep))
        if self.keep_hourly:
            keep.update(prune_split(archives, '%Y-%m-%d %H', self.keep_hourly, keep))
        if self.keep_daily:
            keep.update(prune_split(archives, '%Y-%m-%d', self.keep_daily, keep))
        if self.keep_weekly:
            keep.update(prune_split(archives, '%G-%V', self.keep_weekly, keep))
        if self.keep_monthly:
            keep.update(prune_split(archives, '%Y-%m', self.keep_monthly, keep))
        if self.keep_yearly:
            keep.update(prune_split(archives, '%Y', self.keep_yearly, keep))

        archives = [(archive not in keep, archive) for archive in archives]
        return archives

    class Form(forms.Form):
        name = forms.CharField()
        description = forms.CharField(widget=forms.Textarea, required=False, initial='')

        keep_secondly = KeepField(initial=0)
        keep_minutely = KeepField(initial=0)
        keep_hourly = KeepField(initial=0)
        keep_daily = KeepField()
        keep_weekly = KeepField()
        keep_monthly = KeepField()
        keep_yearly = KeepField()

    class ChoiceField(forms.ChoiceField):
        @staticmethod
        def get_choices():
            for policy in prune_root().policies:
                yield policy.oid, str(policy)

        def __init__(self, **kwargs):
            super().__init__(choices=self.get_choices, **kwargs)

        def clean(self, value):
            value = super().clean(value)
            for policy in prune_root().policies:
                if policy.oid == value:
                    return policy
            else:
                raise ValidationError(self.error_messages['invalid_choice'], code='invalid_choice')

        def prepare_value(self, value):
            if not value:
                return
            return value.oid


class PruneConfig(Evolvable):
    def __init__(self, name, retention_policy: RetentionPolicy, client_re, description=''):
        """
        *clients* can either be iterable or callable; in the latter case it is called to iterate over the clients.
        """
        self.name = name
        self.description = description
        self.retention_policy = retention_policy
        self.client_re = client_re

    def __str__(self):
        return self.name

    def clients(self):
        client_re = re.compile(self.client_re, re.IGNORECASE)
        for hostname, client in data_root().clients.items():
            if not client_re.fullmatch(hostname):
                continue
            log.debug('Matched client %s to pattern %r', hostname, self.client_re)
            yield client

    def archives(self):
        for client in self.clients():
            yield from client.archives.values()

    def apply_policy(self):
        archives = list(self.archives())
        return self.retention_policy.apply(archives)

    def prune(self):
        all_archives = self.apply_policy()
        stats = {}

        for archives in groupby(all_archives, lambda archive: archive.repository):
            archives = list(archives)
            repository = archives[0].repository
            stats[repository] = self.prune_archives(archives, repository)

        return stats

    def prune_archives(self, archives, repository):
        """
        Prune list of two tuples (delete, archive), all of which must be in the same `Repository`.

        Return `Statistics`.
        """
        stats = Statistics()
        with open_repository(repository) as borg_repository:
            manifest, key = Manifest.load(borg_repository)
            with Cache(borg_repository, key, manifest, lock_wait=1) as cache:
                for delete, archive in archives:
                    assert archive.repository == repository
                    if delete:
                        log.info('Deleting archive %s [%s]', archive.name, archive.fpr)
                        archive.delete(manifest)
                    else:
                        log.info('Skipping archive %s [%s]', archive.name, archive.fpr)
                manifest.write()
                repository.commit()
                cache.commit()
        log.error(stats.summary.format(label='Deleted data:', stats=stats))
        return stats

    class Form(forms.Form):
        name = forms.CharField()
        description = forms.CharField(widget=forms.Textarea, required=False, initial='')

        retention_policy = RetentionPolicy.ChoiceField()

        client_re = forms.CharField(
            validators=[validate_regex],
            initial='.*',
            label=_('Regex for selecting clients'),
        )


class PruneJobExecutor(JobExecutor):
    @classmethod
    def run(cls, job):
        executor = cls(job)
        executor.execute(job)

    def execute(self, job):
        pass


class PruneJob(Job):
    short_name = 'prune'
    executor = PruneJobExecutor

    class State(Job.State):
        prune = s('prune', _('Pruning archives'))
