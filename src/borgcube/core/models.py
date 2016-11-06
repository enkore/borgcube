import enum
import logging
import re
import uuid

from django.core import validators
from django.db import models, transaction
from django.utils.translation import ugettext_lazy as _

from jsonfield.fields import TypedJSONField, JSONField

from borg.helpers import Location

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
    id = CharField(verbose_name=_('Repository ID'), help_text=_('32 bytes in hex'), primary_key=True)
    name = CharField()
    url = CharField(max_length=1000, help_text=_('For example /data0/reposity or user@storage:/path.'))

    @property
    def location(self):
        return Location(self.url)

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

    job = models.ForeignKey('Job', null=True, blank=True)


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
    @enum.unique
    class State(ModelEnum):
        job_created = 'job-created'

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
        # Server syncs it's cache
        cache_sync = 'cache_sync'

        done = 'done'

        failed = 'failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    repository = models.ForeignKey(Repository)
    client = models.ForeignKey(Client, related_name='jobs')
    config = models.ForeignKey(JobConfig, blank=True, null=True)

    data = JSONField()

    state = CharField(default='job-created', choices=State.choices())

    @property
    def archive_name(self):
        return self.client.hostname + '-' + str(self.id)

    def failed(self):
        return True   # self. outcome == ...

    def update_state(self, previous, to):
        with transaction.atomic():
            self.refresh_from_db()
            if self.state != previous.value:
                raise ValueError('Cannot transition job state from %r to %r, because current state is %r'
                                 % (previous.value, to.value, self.state))
            self.state = to.value
            self.save()
            log.info('%s: phase %s -> %s', self.id, previous.value, to.value)

    class Meta:
        ordering = ['-timestamp']
