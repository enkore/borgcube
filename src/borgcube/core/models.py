import datetime
import hmac
import inspect
import logging
import re
from hashlib import sha224
from pathlib import Path

from django.conf import settings
from django.core import validators
from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.utils import timezone
from django import forms

import persistent
import transaction
from BTrees.LOBTree import LOBTree as TimestampTree
from BTrees.LOBTree import LOBTree
from BTrees.OOBTree import OOBTree
from persistent.list import PersistentList

from recurrence.forms import RecurrenceField

from borg.helpers import Location

import borgcube
from borgcube.utils import data_root

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


def evolve(from_version=1, to_version=None):
    def decorator(function):
        try:
            function._evolves_from = tuple(from_version)
        except TypeError:
            function._evolves_from = from_version,
        function._evolves_to = to_version
        return function
    return decorator


class StringObjectID:
    @property
    def oid(self):
        return self._p_oid.hex()


class Updateable:
    def _update(self, d):
        self.__dict__.update(d)
        self._p_changed = True


class Volatility:
    _volatile = ()

    def __getstate__(self):
        state = super().__getstate__()
        for volatile in self._volatile:
            state.pop(volatile, None)
        return state


class Evolvable(persistent.Persistent, StringObjectID, Updateable):
    version = 1

    def __setstate__(self, state):
        if state['version'] != self.version:
            def evolves(member):
                is_method = inspect.ismethod(member)
                if not is_method:
                    return False
                return hasattr(member, '_evolves_from') and hasattr(member, '_evolves_to')

            log.debug('Evolving object %r from version %d to version %d', self, state['version'], self.version)
            transitory_sacrifices = list(zip(*inspect.getmembers(self, predicate=evolves)))[1]
            log.debug('Possible evolutionary paths are: %s', ', '.join(f.__name__ for f in transitory_sacrifices))
            while state['version'] != self.version:
                possible_evolution = []
                for evolve in transitory_sacrifices:
                    if state['version'] in evolve._evolves_from:
                        possible_evolution.append(evolve)
                possible_evolution.sort(key=lambda evolve: evolve._evolves_to)
                evolve = possible_evolution.pop()
                log.debug('Evolution is at version %d, next mutation is %s', state['version'], evolve.__name__)
                state = evolve(state)
                state['version'] = evolve._evolves_to
            log.debug('Evolution completed.')

        try:
            super().__setstate__(state)
        except AttributeError:
            self.__dict__.update(state)

    def __getstate__(self):
        try:
            state = super().__getstate__()
        except AttributeError:
            state = self.__dict__.copy()
        state.setdefault('version', self.version)
        return state


class DataRoot(Evolvable):
    def __init__(self):
        self.repositories = PersistentList()
        # hex archive id -> Archive
        self.archives = OOBTree()
        # client hostname -> Client
        self.clients = OOBTree()

        # job timestamp -> Job
        self.jobs = TimestampTree()
        # job state (str) -> TimestampTree
        self.jobs_by_state = OOBTree()

        self.schedules = PersistentList()


class Repository(Evolvable):
    name = ''
    description = ''

    url = ''

    # 32 bytes in hex
    repository_id = ''

    remote_borg = 'borg'

    def __init__(self, name, url, description='', repository_id='', remote_borg='borg'):
        self.name = name
        self.url = url
        self.description = description
        self.repository_id = repository_id
        self.remote_borg = remote_borg
        self.jobs = TimestampTree()
        self.archives = OOBTree()

    @property
    def location(self):
        return Location(self.url)

    def latest_job(self):
        try:
            return self.jobs[self.jobs.maxKey()]
        except ValueError:
            return

    class Form(forms.Form):
        name = forms.CharField()
        description = forms.CharField(widget=forms.Textarea, required=False)
        url = forms.CharField(help_text=_('For example /data0/repository or user@storage:/path.'), label=_('URL'))
        repository_id = forms.CharField(min_length=64, max_length=64, label=_('Repository ID'))
        remote_borg = forms.CharField(help_text=_('Remote borg binary name (only applies to remote repositories).'))


class Archive(Evolvable):
    def __init__(self, id, repository, name, client=None,
                 comment='',
                 nfiles=0, original_size=0, compressed_size=0, deduplicated_size=0,
                 duration=datetime.timedelta()):
        self.id = id
        self.repository = repository
        self.name = name
        self.comment = comment
        self.nfiles = nfiles
        self.original_size = original_size
        self.compressed_size = compressed_size
        self.deduplicated_size = deduplicated_size
        self.duration = duration
        data_root().archives[id] = self
        repository.archives[id] = self
        if client:
            client.archives[id] = self


class RshClientConnection(Evolvable):
    # 'Usually something like root@somehost, but you can also give a .ssh/config host alias, for example.'
    remote = ''

    # RSH
    rsh = 'ssh'
    # RSH options
    rsh_options = None
    # SSH identity file
    ssh_identity_file = None

    # Remote borg binary name
    remote_borg = 'borg'

    # Remote cache directory
    # If not specified the Borg default will be used (usually ~/.cache/borg/).
    remote_cache_dir = None

    def __init__(self, remote,
                 rsh='ssh', rsh_options=None, ssh_identity_file=None,
                 remote_borg='borg', remote_cache_dir=None):
        self.remote = remote
        self.rsh = rsh
        self.rsh_options = rsh_options
        self.ssh_identity_file = ssh_identity_file
        self.remote_borg = remote_borg
        self.remote_cache_dir = remote_cache_dir

    class Form(forms.Form):
        remote = forms.CharField()
        rsh = forms.CharField(initial='ssh')
        rsh_options = forms.CharField(required=False)
        ssh_identity_file = forms.CharField(required=False)
        remote_borg = forms.CharField(initial='borg')
        remote_cache_dir = forms.CharField(required=False)


class Client(Evolvable):
    version = 2

    @evolve(1, 2)
    def add_job_configs(self, state):
        state['job_configs'] = PersistentList()
        return state

    def __init__(self, hostname, description='', connection=None):
        self.hostname = hostname
        self.description = description
        self.connection = connection
        self.jobs = TimestampTree()
        self.archives = OOBTree()
        self.job_configs = PersistentList()
        data_root().clients[hostname] = self

    def latest_job(self):
        try:
            return self.jobs[self.jobs.maxKey()]
        except ValueError:
            return

    class Form(forms.Form):
        hostname = forms.CharField(validators=[slug_validator])
        description = forms.CharField(widget=forms.Textarea, required=False, initial='')


class JobConfig(Evolvable):
    def __init__(self, client, label, repository):
        self.client = client
        self.label = label
        self.repository = repository

    def __str__(self):
        return _('{client}: {label}').format(
            client=self.client.hostname,
            label=self.label,
        )


class s(str):
    def __new__(cls, str, translation):
        obj = super().__new__(cls, str)
        obj.verbose_name = translation
        return obj

    def __getnewargs__(self):
        return str(self), self.verbose_name


class Job(Evolvable):
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

    def __init__(self, repository=None):
        self.created = timezone.now()
        self.timestamp_end = None
        self.timestamp_start = None
        self.repository = repository
        self.state = self.State.job_created
        key = int(self.created.timestamp())
        if repository:
            # TODO better (more resolution, unique)
            repository.jobs[key] = self
        data_root().jobs[key] = self
        data_root().jobs_by_state.setdefault(self.state, TimestampTree())[key] = self

    @property
    def duration(self):
        if self.timestamp_end and self.timestamp_start:
            return self.timestamp_end - self.timestamp_start
        else:
            return timezone.now() - (self.timestamp_start or self.created)

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

    def update_state(self, previous, to):
        with transaction.manager:
            if self.state != previous:
                raise ValueError('Cannot transition job state from %r to %r, because current state is %r'
                                 % (previous, to, self.state))
            borgcube.utils.hook.borgcube_job_pre_state_update(job=self, current_state=previous, target_state=to)
            del data_root().jobs_by_state[self.state][int(self.created.timestamp())]
            self.state = to
            data_root().jobs_by_state.setdefault(self.state, TimestampTree())[int(self.created.timestamp())] = self
            self._check_set_start_timestamp(previous)
            self._check_set_end_timestamp()
            log.debug('%s: phase %s -> %s', self.oid, previous, to)
            borgcube.utils.hook.borgcube_job_post_state_update(job=self, prior_state=previous, current_state=to)

    def force_state(self, state):
        transaction.begin()
        if self.state == state:
            return False
        log.debug('%s: Forced state %s -> %s', self.oid, self.state, state)
        self._check_set_start_timestamp(self.state)
        del data_root().jobs_by_state[self.state][int(self.created.timestamp())]
        self.state = state
        data_root().jobs_by_state.setdefault(self.state, TimestampTree())[int(self.created.timestamp())] = self
        self._check_set_end_timestamp()
        transaction.commit()
        borgcube.utils.hook.borgcube_job_post_force_state(job=self, forced_state=state)
        return True

    def set_failure_cause(self, kind, **kwargs):
        borgcube.utils.hook.borgcube_job_failure_cause(job=self, kind=kind, kwargs=kwargs)
        self.force_state(self.State.failed)
        self.failure_cause = {
            'kind': kind,
        }
        self.failure_cause.update(kwargs)
        transaction.commit()

    def log_path(self):
        short_timestamp = self.created.replace(microsecond=0).isoformat()
        logs_path = Path(settings.SERVER_LOGS_DIR) / str(self.created.year)
        file = self._log_file_name(short_timestamp)
        logs_path.mkdir(parents=True, exist_ok=True)
        return logs_path / file

    def _log_file_name(self, timestamp):
        return '%s-%s-%s' % (timestamp, self.short_name, self.oid)

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
            log.debug('%s: Recording %s as start time', self.oid, self.timestamp_start.isoformat())

    def _check_set_end_timestamp(self):
        if self.state in self.State.STABLE:
            self.timestamp_end = timezone.now()
            log.debug('%s: Recording %s as end time', self.oid, self.timestamp_end.isoformat())

    def __str__(self):
        return str(self.oid)

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


    def __init__(self, repository, client, config):
        super().__init__(repository)
        self.client = client
        client.jobs[int(self.created.timestamp())] = self
        self.archive = None
        self.config = config
        self.checkpoint_archives = PersistentList()

    @property
    def reverse_path(self):
        return hmac.HMAC((settings.SECRET_KEY + 'BackupJob-revloc').encode(),
                         str(self.oid).encode(),
                         sha224).hexdigest()

    @property
    def reverse_location(self):
        return settings.SERVER_LOGIN + ':' + self.reverse_path

    @property
    def archive_name(self):
        return self.client.hostname + '-' + str(self.oid)

    def _log_file_name(self, timestamp):
        return '%s-%s-%s-%s' % (timestamp, self.short_name, self.client.hostname, self.oid)


class CheckConfig(Evolvable):
    def __init__(self, label, repository, check_repository, verify_data, check_archives, check_only_new_archives):
        self.label = label
        self.repository = repository
        self.check_repository = check_repository
        self.verify_data = verify_data
        self.check_archives = check_archives
        self.check_only_new_archives = check_only_new_archives

    class Form(forms.Form):
        label = CharField()
        repository = None  # TODO

        check_repository = forms.BooleanField(initial=True, required=False)
        verify_data = forms.BooleanField(initial=False, required=False, help_text=_('Verify all data cryptographically (slow)'))
        check_archives = forms.BooleanField(initial=True, required=False)

        check_only_new_archives = forms.BooleanField(
            initial=False, required=False,
            help_text=_('Check only archives added since the last check'))


class CheckJob(Job):
    short_name = 'check'

    class State(Job.State):
        repository_check = s('repository_check', _('Checking repository'))
        verify_data = s('verify_data', _('Verifying data'))
        archives_check = s('archives_check', _('Checking archives'))

    def __init__(self, repository, config):
        super().__init__(repository)
        self.config = config


class Schedule(Evolvable):
    def __init__(self, name, recurrence_start, recurrence, description=''):
        self.name = name
        self.description = description

        self.recurrence_start = recurrence_start
        self.recurrence = recurrence

        self.actions = PersistentList()

    class Form(forms.Form):
        name = forms.CharField()
        description = forms.CharField(required=False, initial='')

        recurrence_start = forms.DateTimeField(
            initial=timezone.now,
            help_text=_('The recurrence defined below is applied from this date and time onwards.<br/>'
                        'Eg. for daily recurrence the actions would be scheduled for the time set here.<br/>'
                        'The set time zone is %s.') % settings.TIME_ZONE
        )
        recurrence = RecurrenceField()


class DottedPath:
    @classmethod
    def dotted_path(cls):
        return cls.__module__ + '.' + cls.__qualname__


class ScheduledAction(Evolvable, DottedPath):
    """
    Implement this to add schedulable actions to the scheduler.

    Make sure that your implementation is imported, since these are implicitly
    discovered subclasses.
    """

    name = ''

    class Form(forms.Form):
        """
        The form that should be presented for adding/modifying this action.

        This can be a ModelForm or modify the DB; the transaction is managed for you,
        and no additional transaction management should be needed.

        The usual form rules apply, however, note that .cleaned_data must be JSON
        serializable if .is_valid() returns true. This data will be used for instanciating
        the action class (*py_args*).

        .save() will be called with no arguments regardless of type, if it exists.
        """

    @classmethod
    def form(cls, *args, **kwargs):
        form = cls.Form(*args, **kwargs)
        form.name = cls.name
        form.dotted_path = cls.dotted_path()
        return form

    def __init__(self, schedule):
        self.schedule = schedule

    def __str__(self):
        pass

    def execute(self, apiserver):
        pass

    @classmethod
    def valid_class(cls, dotted_path):
        return any(action_class.dotted_path() == dotted_path for action_class in cls.__subclasses__())


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