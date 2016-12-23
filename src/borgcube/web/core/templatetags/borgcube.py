
from json import dumps

from django import template
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from django.core.serializers.json import DjangoJSONEncoder

from borg.helpers import format_file_size

from borgcube.core import models
from borgcube.utils import hook
from .. import views

register = template.Library()


@register.filter
def field_name(model_instance, field):
    name = model_instance._meta.get_field(field).verbose_name
    if name == field.replace('_', ' '):
        return name.title()
    return name


@register.filter
def help_text(model_instance, field):
    return model_instance._meta.get_field(field).help_text


@register.filter
def get_url(model_instance):
    obj = model_instance
    if not obj:
        return ''
    if isinstance(obj, models.Job):
        return reverse(views.job_view, args=(obj.pk,))
    elif isinstance(obj, models.Client):
        return reverse(views.client_view, args=(obj.pk,))
    elif isinstance(obj, models.JobConfig):
        return reverse(views.client_view, args=(obj.client.pk,)) + '#job-config-%d' % obj.pk
    elif isinstance(obj, models.Repository):
        return reverse(views.repository_view, args=(obj.pk,))
    url = hook.borgcube_web_get_url(obj=obj)
    if not url:
        raise ValueError('Don\'t know how to make URL for %r (type %r)' % (obj, type(obj)))
    return url


@register.filter
def compression_name(compression_id):
    return dict(views.JobConfigForm.COMPRESSION_CHOICES).get(compression_id, compression_id)


@register.filter
def summarize_archive(archive):
    assert isinstance(archive, models.Archive)
    return _('{size_formatted} / {archive.nfiles} files').format(
        archive=archive, size_formatted=format_file_size(archive.original_size))


@register.filter
def job_outcome(job):
    assert isinstance(job, models.Job)
    outcome = hook.borgcube_web_job_outcome(job=job)
    if outcome:
        return outcome
    if job.failed:
        failure_cause = job.data.get('failure_cause')
        if failure_cause:
            failure_kind = failure_cause['kind']
            if failure_kind == 'client-connection-failed':
                return _('Could not connect to client')
            elif failure_kind == 'repository-does-not-exist':
                return _('Repository does not exist')
            elif failure_kind == 'repository-check-needed':
                return _('Repository needs check')
            elif failure_kind == 'repository-enospc':
                return _('Repository ran out of space')
            elif failure_kind == 'cache-lock-timeout':
                return _('Timeout while locking server cache')
            elif failure_kind == 'cache-lock-failed':
                return _('Failed to lock server cache: %s') % failure_cause['error']
            elif failure_kind == 'repository-lock-timeout':
                return _('Timeout while locking repository')
            elif failure_kind == 'repository-lock-failed':
                return _('Failed to lock repository: %s') % failure_cause['error']
            elif failure_kind == 'lock-error':
                return _('Locking error')
            elif failure_kind == 'client-borg-outdated':
                return _('Borg on the client is outdated')
            elif failure_kind == 'borgcubed-restart':
                return _('borgcubed terminated/restarted')
            else:
                return failure_kind
        else:
            return _('Unknown error - see logs')
    elif isinstance(job, models.BackupJob) and job.archive:
        return _('{statename} ({archive_summary})').format(
            statename=job.State.verbose_name(job.state), archive_summary=summarize_archive(job.archive))
    else:
        return job.State.verbose_name(job.state)


@register.filter
def format_timedelta(td):
    ts = td.total_seconds()
    s = ts % 60
    m = int(ts / 60) % 60
    h = int(ts / 3600) % 24
    if td.days and h and m and s:
        return _('%d days %d hours %d minutes %d seconds') % (td.days, h, m, s)
    elif h and m and s:
        return _('%d hours %d minutes %d seconds') % (h, m, s)
    elif m and s:
        return _('%d minutes %d seconds') % (m, s)
    else:
        return _('%d seconds') % s


@register.filter
def get(obj, attr):
    """Look value of an object up through a variable (instead of a fixed name as in obj.a)"""
    try:
        return obj.get(attr)
    except AttributeError:
        return getattr(obj, attr)


@register.filter
def json(obj):
    """Return safe JSON serialization of *obj*."""
    return mark_safe(dumps(obj, cls=DjangoJSONEncoder))
