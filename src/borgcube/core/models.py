import enum
import logging
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.core import validators
from django.db import models, transaction
from django.utils.translation import ugettext_lazy as _
from django.utils import timezone

from jsonfield.fields import TypedJSONField, JSONField

from borg.helpers import Location

import borgcube

log = logging.getLogger(__name__)


def CharField(*args, **kwargs):
    if 'max_length' not in kwargs:
        kwargs['max_length'] = 200
    return models.CharField(*args, **kwargs)


slug_validator = validators.RegexValidator(
    regex=re.compile(r'^[-_.\w]+$'),
    message=_('Enter a valid identifier consisting of letters, numbers, dashes, underscores or dots (._-).'),
    code='invalid'
)


class SlugWithDotField(models.CharField):
    """
    A SlugField where dots are allowed.

    This makes it compatible with hostnames and FQDNs.
    """
    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = kwargs.get('max_length', 200)
        super().__init__(*args, **kwargs)

    default_error_messages = {
        'invalid': u"Enter a valid 'slug' consisting of letters, numbers, "
                   u"underscores, dots or hyphens.",
    }
    default_validators = [slug_validator]


class Repository(models.Model):
    name = CharField()
    description = models.TextField(blank=True)

    url = CharField(max_length=1000, help_text=_('For example /data0/reposity or user@storage:/path.'))
    repository_id = CharField(verbose_name=_('Repository ID'), help_text=_('32 bytes in hex'))

    remote_borg = CharField(default='borg', verbose_name=_('Remote borg binary name (only applies to remote repositories)'))

    @property
    def location(self):
        return Location(self.url)

    def latest_job(self):
        return self.jobs.all()[:1].get()

    def __str__(self):
        return self.name


class Archive(models.Model):
    id = CharField(primary_key=True)
    repository = models.ForeignKey(Repository, db_index=True)
    name = CharField()
    comment = models.TextField(blank=True)

    nfiles = models.BigIntegerField()
    original_size = models.BigIntegerField()
    compressed_size = models.BigIntegerField()
    deduplicated_size = models.BigIntegerField()
    duration = models.DurationField()


class ClientConnection(models.Model):
    remote = CharField(help_text=_('Usually something like root@somehost, but you can also give a .ssh/config host alias, for example.'))

    rsh = CharField(default='ssh', verbose_name=_('RSH'))
    rsh_options = CharField(default=None, blank=True, null=True, verbose_name=_('RSH options'))
    ssh_identity_file = CharField(default=None, blank=True, null=True, verbose_name=_('SSH identity file'))
    remote_borg = CharField(default='borg', verbose_name=_('Remote borg binary name'))
    remote_cache_dir = CharField(default=None, blank=True, null=True, verbose_name=_('Remote cache directory'),
                                 help_text=_('If not specified the Borg default will be used (usually ~/.cache/borg/).'))


class Client(models.Model):
    hostname = SlugWithDotField(primary_key=True, verbose_name=_('Hostname'),
                                help_text=_('Only letters and numbers (A-Z, 0-9), dashes, underscores and dots (._-).'))
    name = CharField()
    description = models.TextField(blank=True)

    connection = models.OneToOneField(ClientConnection)

    def latest_job(self):
        return self.jobs.all()[:1].get()


class JobConfig(models.Model):
    client = models.ForeignKey(Client, related_name='job_configs')
    repository = models.ForeignKey(Repository, related_name='job_configs')

    config = TypedJSONField(required_fields={
        'version': int,
    }, validators=[
        lambda config: config['version'] == 1,
    ], default={
        'version': 1,
    })


class ModelEnum(enum.Enum):
    @classmethod
    def choices(cls):
        return [(e.value, e.name) for e in cls.__members__.values()]


class Job(models.Model):
    """
    Core job model.

    A job is some kind of task that is run by borgcubed. Normally these are concerned with
    a repository, but if that's not the case - the field is nullable.

    Steps to implement a Job class:

    1. Derive from this
    2. Define enum.Enum called State
    3. The State enum needs at least job_created, failed, done
    4. The State enum needs an attribute STABLE, which should be a tuple of stable end-states, usually::

        State.STABLE = (State.job_created, State.done, State.failed)

    5. borgcubed needs to know how to run the job, therefore implement the borgcubed_job_executor hook.
       Also, implement the required JobExecutor class.
    6. You also want to implement a borgcubed command through borgcubed_handle_request to actually queue
       your job for execution (unless it always runs off a schedule).
    7. Other relevant hooks: borgcube_job_blocked, borgcubed_job_exit.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    timestamp_start = models.DateTimeField(blank=True, null=True)
    timestamp_end = models.DateTimeField(blank=True, null=True)

    repository = models.ForeignKey(Repository, related_name='jobs', blank=True, null=True)

    @property
    def duration(self):
        if self.timestamp_end and self.timestamp_start:
            return self.timestamp_end - self.timestamp_start
        else:
            return timezone.now() - (self.timestamp_start or self.created)

    db_state = CharField(default='job-created')

    data = JSONField()

    @property
    def state(self):
        return self.State(self.db_state)

    @property
    def failed(self):
        return self.state == self.State.failed

    @property
    def done(self):
        return self.state == self.State.done

    def update_state(self, previous, to):
        with transaction.atomic():
            self.refresh_from_db()
            if self.db_state != previous.value:
                raise ValueError('Cannot transition job state from %r to %r, because current state is %r'
                                 % (previous.value, to.value, self.db_state))
            borgcube.utils.hook.borgcube_job_pre_state_update(job=self, current_state=previous, target_state=to)
            self.db_state = to.value
            self._check_set_start_timestamp(previous)
            self._check_set_end_timestamp()
            self.save()
            log.debug('%s: phase %s -> %s', self.id, previous.value, to.value)
            borgcube.utils.hook.borgcube_job_post_state_update(job=self, prior_state=previous, current_state=to)

    def force_state(self, state):
        self.refresh_from_db()
        if self.db_state == state.value:
            return False
        log.debug('%s: Forced state %s -> %s', self.id, self.db_state, state.value)
        self._check_set_start_timestamp(self.state)
        self.db_state = state.value
        self._check_set_end_timestamp()
        self.save()
        borgcube.utils.hook.borgcube_job_post_force_state(job=self, forced_state=state)
        return True

    def set_failure_cause(self, kind, **kwargs):
        borgcube.utils.hook.borgcube_job_failure_cause(job=self, kind=kind, kwargs=kwargs)
        self.force_state(self.State.failed)
        self.data['failure_cause'] = {
            'kind': kind,
        }
        self.data['failure_cause'].update(kwargs)
        self.save()

    def log_path(self):
        short_timestamp = self.created.replace(microsecond=0).isoformat()
        logs_path = Path(settings.SERVER_LOGS_DIR) / str(self.created.year)
        file = short_timestamp + '-' + self.client.hostname  + '-' + str(self.id)
        logs_path.mkdir(parents=True, exist_ok=True)
        return logs_path / file

    def delete(self, using=None, keep_parents=False):
        borgcube.utils.hook.borgcube_job_pre_delete(job=self)
        super().delete(using, keep_parents)
        try:
            self.log_path().unlink()
        except OSError:
            pass

    def _check_set_start_timestamp(self, from_state):
        if from_state == self.State.job_created:
            self.timestamp_start = timezone.now()
            log.debug('%s: Recording %s as start time', self.id, self.timestamp_start.isoformat())

    def _check_set_end_timestamp(self):
        if self.state in self.State.STABLE:
            self.timestamp_end = timezone.now()
            log.debug('%s: Recording %s as end time', self.id, self.timestamp_end.isoformat())

    def __str__(self):
        return str(self.id)

    class Meta:
        ordering = ['-created']


class BackupJob(Job):
    @enum.unique
    class State(enum.Enum):
        job_created = 'job-created'
        done = 'done'
        failed = 'failed'

        # Cache is uploaded to client
        client_preparing = 'client-preparing'
        # Cache upload done, borg-create will be started
        client_prepared = 'client-prepared'
        # borg-create has connected to reverse proxy
        client_in_progress = 'client-in-progress'
        # borg-create is done
        client_done = 'client-done'
        # Cache is removed from client
        client_cleanup = 'client-cleanup'

    State.STABLE = (State.job_created, State.done, State.failed)

    State.job_created.verbose_name = _('Job created')
    State.done.verbose_name = _('Finished')
    State.failed.verbose_name = _('Failed')
    State.client_preparing.verbose_name = _('Preparing client')
    State.client_prepared.verbose_name = _('Prepared client')
    State.client_in_progress.verbose_name =_('In progress')
    State.client_done.verbose_name = _('Client is done')
    State.client_cleanup.verbose_name = _('Client is cleaned up')

    client = models.ForeignKey(Client, related_name='jobs')
    archive = models.OneToOneField(Archive, blank=True, null=True)
    config = models.ForeignKey(JobConfig, blank=True, null=True)

    @property
    def archive_name(self):
        return self.client.hostname + '-' + str(self.id)


class CheckConfig(models.Model):
    repository = models.ForeignKey(Repository, related_name='check_configs')

    check_repository = models.BooleanField(default=True)
    verify_data = models.BooleanField(default=False, help_text=_('Verify all data cryptographically (slow)'))
    check_archives = models.BooleanField(default=True)

    check_only_new_archives = models.BooleanField(default=False, help_text=_('Check only archives added since the last check'))


class CheckJob(Job):
    @enum.unique
    class State(enum.Enum):
        job_created = 'job-created'
        done = 'done'
        failed = 'failed'

        repository_check = 'repository-check'
        verify_data = 'verify-data'
        archives_check = 'archives-check'

    State.STABLE = (State.job_created, State.done, State.failed)

    State.job_created.verbose_name = _('Job created')
    State.done.verbose_name = _('Finished')
    State.failed.verbose_name = _('Failed')
    State.repository_check.verbose_name = _('Checking repository')
    State.verify_data.verbose_name = _('Verifying data')
    State.archives_check.verbose_name = _('Checking archives')

    config = models.ForeignKey(CheckConfig, blank=True, null=True)


class ScheduleItem(models.Model):
    py_class = models.CharField(max_length=100)
    py_args = JSONField()

    name = CharField()
