import enum
import hmac
import logging
import re
from hashlib import sha224
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core import validators
from django.db import models, transaction
from django.db.models import QuerySet
from django.utils.translation import ugettext_lazy as _
from django.utils import timezone

from jsonfield.fields import TypedJSONField, JSONField

from recurrence.fields import RecurrenceField

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


class DowncastQuerySet(QuerySet):
    def iterator(self):
        for obj in super().iterator():
            yield obj._downcast()


DowncastManager = models.manager.BaseManager.from_queryset(DowncastQuerySet)


class DowncastModel(models.Model):
    objects = DowncastManager()
    _concrete_model = models.ForeignKey(ContentType)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self._concrete_model = ContentType.objects.get_for_model(type(self))
        super().save(*args, **kwargs)

    def _downcast(self):
        return self._concrete_model.get_object_for_this_type(pk=self.pk)

    class Meta:
        abstract = True


class s(str):
    def __new__(cls, str, translation):
        obj = super().__new__(cls, str)
        obj.verbose_name = translation
        return obj


class Job(DowncastModel):
    """
    Core job model.

    A job is some kind of task that is run by borgcubed. Normally these are concerned with
    a repository, but if that's not the case - the field is nullable.

    Steps to implement a Job class:

    1. Derive from this
    2. Define additional states, if necessary, by deriving the State class in your model from Job.State
    3. borgcubed needs to know how to run the job, therefore implement the borgcubed_job_executor hook.
       Also, implement the required JobExecutor class.
    4. You also want to implement a borgcubed command through borgcubed_handle_request to actually queue
       your job for execution (unless it always runs off a schedule).
    5. Other relevant hooks: borgcube_job_blocked, borgcubed_job_exit.
    """
    short_name = 'job'

    class State:
        job_created = s('job_created', _('Job created'))
        done = s('done', _('Finished'))
        failed = s('failed', _('Failed'))
        cancelled = s('cancelled', _('Cancelled'))

        STABLE = {job_created, done, failed, cancelled}

        @classmethod
        def verbose_name(cls, name):
            return getattr(cls, name).verbose_name

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

    state = CharField(default=State.job_created)

    data = JSONField()

    @property
    def verbose_name(self):
        return self._meta.verbose_name

    @property
    def failed(self):
        return self.state == self.State.failed

    @property
    def done(self):
        return self.state == self.State.done

    @property
    def stable(self):
        return self.state in self.State.STABLE

    def is_blocked(self):
        if self.repository:
            blocking_jobs = self.objects.filter(repository=self.repository)
        else:
            blocking_jobs = self.objects.all()
        blocking_jobs = blocking_jobs.exclude(state__in=self.State.STABLE)
        job_is_blocked = blocking_jobs.exists()
        if job_is_blocked:
            log.debug('Job %s blocked by running backup jobs: %s', self.id,
                      ' '.join('{} ({})'.format(job.id, job.state) for job in blocking_jobs))
        return job_is_blocked

    def update_state(self, previous, to):
        with transaction.atomic():
            self.refresh_from_db()
            if self.state != previous:
                raise ValueError('Cannot transition job state from %r to %r, because current state is %r'
                                 % (previous, to, self.state))
            borgcube.utils.hook.borgcube_job_pre_state_update(job=self, current_state=previous, target_state=to)
            self.state = to
            self._check_set_start_timestamp(previous)
            self._check_set_end_timestamp()
            self.save()
            log.debug('%s: phase %s -> %s', self.id, previous, to)
            borgcube.utils.hook.borgcube_job_post_state_update(job=self, prior_state=previous, current_state=to)

    def force_state(self, state):
        self.refresh_from_db()
        if self.state == state:
            return False
        log.debug('%s: Forced state %s -> %s', self.id, self.state, state)
        self._check_set_start_timestamp(self.state)
        self.state = state
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
        file = self._log_file_name(short_timestamp)
        logs_path.mkdir(parents=True, exist_ok=True)
        return logs_path / file

    def _log_file_name(self, timestamp):
        return '%s-%s-%s' % (timestamp, self.short_name, self.id)

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
    short_name = 'backup'

    class State(Job.State):
        # Cache is uploaded to client
        client_preparing = s('client_preparing', _('Preparing client'))
        # Cache upload done, borg-create will be started
        client_prepared = s('client_prepared', _('Prepared client'))
        # borg-create has connected to reverse proxy
        client_in_progress = s('client_in_progress', _('In progress'))
        # borg-create is done
        client_done = s('client_done', _('Client is done'))
        # Cache is removed from client
        client_cleanup = s('client_cleanup', _('Client is cleaned up'))

    client = models.ForeignKey(Client, related_name='jobs')
    archive = models.OneToOneField(Archive, blank=True, null=True)
    config = JSONField()

    @property
    def reverse_path(self):
        return hmac.HMAC((settings.SECRET_KEY + 'BackupJob-revloc').encode(),
                         str(self.id).encode(),
                         sha224).hexdigest()

    @property
    def reverse_location(self):
        return settings.SERVER_LOGIN + ':' + self.reverse_path

    def get_jobconfig(self):
        try:
            return JobConfig.objects.get(id=self.config.get('id'))
        except JobConfig.DoesNotExist:
            return

    @property
    def archive_name(self):
        return self.client.hostname + '-' + str(self.id)

    @classmethod
    def from_config(cls, job_config):
        config = dict(job_config.config)
        config['id'] = job_config.id
        return cls(
            client=job_config.client,
            repository=job_config.repository,
            config=config,
        )

    def _log_file_name(self, timestamp):
        return '%s-%s-%s-%s' % (timestamp, self.short_name, self.client.hostname, self.id)


class CheckConfig(models.Model):
    label = CharField()
    repository = models.ForeignKey(Repository, related_name='check_configs')

    check_repository = models.BooleanField(default=True)
    verify_data = models.BooleanField(default=False, help_text=_('Verify all data cryptographically (slow)'))
    check_archives = models.BooleanField(default=True)

    check_only_new_archives = models.BooleanField(default=False, help_text=_('Check only archives added since the last check'))

    def to_dict(self):
        return {
            'id': self.id,
            'check_repository': self.check_repository,
            'verify_data': self.verify_data,
            'check_archives': self.check_archives,
            'check_only_new_archives': self.check_only_new_archives,
        }


class CheckJob(Job):
    short_name = 'check'

    class State(Job.State):
        repository_check = s('repository_check', _('Checking repository'))
        verify_data = s('verify_data', _('Verifying data'))
        archives_check = s('archives_check', _('Checking archives'))

    config = JSONField()

    @classmethod
    def from_config(cls, check_config):
        config = check_config.to_dict()
        return cls(
            repository=check_config.repository,
            config=check_config.to_dict()
        )


class ScheduleItem(models.Model):
    py_class = models.CharField(max_length=100)
    py_args = JSONField()

    name = CharField()
    description = models.TextField(blank=True)

    recurrence_start = models.DateTimeField(default=timezone.now)
    recurrence = RecurrenceField()
