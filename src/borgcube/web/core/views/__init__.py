import logging
import json

from django import forms
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.module_loading import import_string
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _

import transaction

from ..models import OverviewMetric
from ..metrics import Metric

from borgcube.core.models import Client, Repository, RshClientConnection
from borgcube.core.models import Job, JobConfig
from borgcube.core.models import Schedule, ScheduledAction
from borgcube.daemon.client import APIClient
from borgcube.utils import data_root, find_oid_or_404

from borgcube.daemon.checkjob import CheckConfig

log = logging.getLogger(__name__)


def fetch_metrics():
    metrics = []
    for metric in OverviewMetric.objects.all()[:]:
        try:
            MetricClass = import_string(metric.py_class)
            if not issubclass(MetricClass, Metric):
                raise ImportError('Not a Metric')
        except ImportError as ie:
            log.error('Could not import metric %r: %s', metric.py_class, ie)
            metric.delete()
            continue
        instance = MetricClass()
        metrics.append({
            'label': metric.label,
            'value': instance.formatted_value(),
        })
    return metrics


def dashboard(request):
    recent_jobs = []
    jobs = data_root().jobs
    try:
        key = jobs.maxKey()
    except KeyError:
        pass
    else:
        while len(recent_jobs) < 20:
            recent_jobs.append(jobs.pop(key))
            try:
                key = jobs.maxKey(key)
            except KeyError:
                break
    transaction.abort()

    return TemplateResponse(request, 'core/dashboard.html', {
        'metrics': fetch_metrics(),
        'recent_jobs': recent_jobs,
    })


def clients(request):
    clients = data_root().clients.values()
    return TemplateResponse(request, 'core/client/list.html', {
        'm': Client,
        'clients': clients,
    })


def paginate(request, things, num_per_page=40, prefix=''):
    if prefix:
        prefix += '_'
    paginator = Paginator(things, num_per_page)
    page = request.GET.get(prefix + 'page')
    try:
        return paginator.page(page)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


def client_view(request, client_id):
    client = data_root().clients[client_id]
    jobs = paginate(request, client.jobs.values(), prefix='jobs')

    return TemplateResponse(request, 'core/client/view.html', {
        'client': client,
        'jobs': jobs,
    })


def client_add(request):
    data = request.POST or None
    client_form = Client.Form(data)
    connection_form = RshClientConnection.Form(data)
    if data and client_form.is_valid() and connection_form.is_valid():
        connection = RshClientConnection(**connection_form.cleaned_data)
        client = Client(connection=connection, **client_form.cleaned_data)
        transaction.commit()
        return redirect(client_view, client.hostname)
    return TemplateResponse(request, 'core/client/add.html', {
        'client_form': client_form,
        'connection_form': connection_form,
    })


def client_edit(request, client_id):
    client = data_root().clients[client_id]
    data = request.POST or None
    client.connection._p_activate()
    client_form = Client.Form(data, initial=client.__dict__)
    del client_form.fields['hostname']
    connection_form = RshClientConnection.Form(data, initial=client.connection.__dict__)
    if data and client_form.is_valid() and connection_form.is_valid():
        client._update(client_form.cleaned_data)
        client.connection._update(connection_form.cleaned_data)
        transaction.commit()
        return redirect(client_view, client.hostname)
    return TemplateResponse(request, 'core/client/edit.html', {
        'client': client,
        'client_form': client_form,
        'connection_form': connection_form,
    })


def job_view(request, job_id):
    job = get_object_or_404(Job, id=job_id)


def job_cancel(request, job_id):
    job = data_root()._p_jar[bytes.fromhex(job_id)]
    if int(job.created.timestamp()) not in data_root().jobs:
        raise Http404
    daemon = APIClient()
    daemon.cancel_job(job)
    return redirect(client_view, job.client.hostname)


def repositories_as_choices():
    for repository in data_root().repositories:
        yield repository.oid, repository.name


class JobConfigForm(forms.Form):
    COMPRESSION_CHOICES = [
        ('none', _('No compression')),
        ('lz4', _('LZ4 (fast)')),
    ] \
        + [('zlib,%d' % level, _('zlib level %d') % level) for level in range(1, 10)] \
        + [('lzma,%d' % level, _('LZMA level %d') % level) for level in range(1, 7)]

    label = forms.CharField()

    repository = Repository.ChoiceField()

    one_file_system = forms.BooleanField(initial=True, required=False,
                                         help_text=_('Don\'t cross over file system boundaries.'))

    compression = forms.ChoiceField(initial='lz4', choices=COMPRESSION_CHOICES,
                                    help_text=_('Compression is performed on the client, not on the server.'))

    paths = forms.CharField(widget=forms.Textarea,
                            help_text=_('Paths to include in the backup, one per line. At least one path is required.'))

    # TODO explain format
    excludes = forms.CharField(widget=forms.Textarea, required=False,
                               help_text=_('Patterns to exclude from the backup, one per line.'))

    class AdvancedForm(forms.Form):
        prefix = 'advanced'

        # TODO DurationField instead?
        checkpoint_interval = forms.IntegerField(min_value=0, initial=1800)

        read_special = forms.BooleanField(initial=False, required=False,
                                          help_text=_('Open and read block and char device files as well as FIFOs as if '
                                                      'they were regular files. Also follow symlinks pointing to these '
                                                      'kinds of files.'))
        ignore_inode = forms.BooleanField(initial=False, required=False,
                                          help_text=_('Ignore inode data in the file metadata cache used to detect '
                                                      'unchanged file.'))
        extra_options = forms.CharField(required=False,
                                        help_text=_('These options are passed verbatim to Borg on the client. Please '
                                                    'don\'t specify any logging options or --remote-path.'))


def job_config_add(request, client_id):
    client = data_root().clients[client_id]
    data = request.POST or None
    form = JobConfigForm(data=data)
    advanced_form = JobConfigForm.AdvancedForm(data=data)
    if data and form.is_valid() and advanced_form.is_valid():
        config = form.cleaned_data
        config.update(advanced_form.cleaned_data)
        config['paths'] = config.get('paths', '').split('\n')
        config['excludes'] = [s for s in config.get('excludes', '').split('\n') if s]

        repository = config.pop('repository')
        job_config = JobConfig(client=client, repository=repository, label=config['label'])
        job_config._update(config)
        client.job_configs.append(job_config)
        transaction.commit()

        # TODO StringListValidator
        # TODO Pattern validation
        # TODO fancy pattern editor with test area

        return redirect(reverse(client_view, args=[client.hostname]) + '#jobconfig-%s' % job_config.oid)
    return TemplateResponse(request, 'core/client/config_add.html', {
        'form': form,
        'advanced_form': advanced_form,
    })


def job_config_edit(request, client_id, config_id):
    client = data_root().clients[client_id]
    job_config = find_oid_or_404(client.job_configs, config_id)
    data = request.POST or None
    job_config._p_activate()
    initial_data = dict(job_config.__dict__)
    initial_data['paths'] = '\n'.join(initial_data['paths'])
    initial_data['excludes'] = '\n'.join(initial_data['excludes'])
    form = JobConfigForm(data=data, initial=initial_data)
    advanced_form = JobConfigForm.AdvancedForm(data=data, initial=initial_data)
    if data and form.is_valid() and advanced_form.is_valid():
        config = form.cleaned_data
        config.update(advanced_form.cleaned_data)
        config['paths'] = config.get('paths', '').split('\n')
        config['excludes'] = [s for s in config.get('excludes', '').split('\n') if s]
        job_config._update(config)
        # TODO StringListValidator
        # TODO Pattern validation
        # TODO fancy pattern editor with test area
        transaction.commit()
        return redirect(reverse(client_view, args=[job_config.client.hostname]) + '#jobconfig-%s' % job_config.oid)
    return TemplateResponse(request, 'core/client/config_edit.html', {
        'client': client,
        'form': form,
        'advanced_form': advanced_form,
        'job_config': job_config,
    })


def job_config_delete(request, client_id, config_id):
    client = data_root().clients[client_id]
    job_config = find_oid_or_404(client.job_configs, config_id)
    if request.method == 'POST':
        client.job_configs.remove(job_config)
        # Could just leave it there, but likely not the intention behind clicking (delete).
        for schedule in data_root().schedules:
            for action in list(schedule.actions):
                if getattr(action, 'job_config', None) == job_config:
                    schedule.actions.remove(action)
        transaction.commit()
    return redirect(client_view, client_id)


def job_config_trigger(request, client_id, config_id):
    client = data_root().clients[client_id]
    config = find_oid_or_404(client.job_configs, config_id)
    if request.method == 'POST':
        daemon = APIClient()
        job = daemon.initiate_backup_job(client, config)
    return redirect(client_view, client_id)


def repositories(request):
    return TemplateResponse(request, 'core/repository/list.html', {
        'm': Repository,
        'repositories': data_root().repositories,
    })


def repository_view(request, repository_id):
    repository = Repository.oid_get(repository_id)
    return TemplateResponse(request, 'core/repository/view.html', {
        'repository': repository,
    })


def repository_edit(request, repository_id):
    repository = Repository.oid_get(repository_id)
    data = request.POST or None
    repository._p_activate()
    repository_form = Repository.Form(data, initial=repository.__dict__)
    if data and repository_form.is_valid():
        repository._update(repository_form.cleaned_data)
        transaction.commit()
        return redirect(repository_view, repository.oid)
    return TemplateResponse(request, 'core/repository/edit.html', {
        'repository': repository,
        'repository_form': repository_form,
    })


def repository_add(request):
    data = request.POST or None
    repository_form = Repository.Form(data)
    if data and repository_form.is_valid():
        repository = Repository(**repository_form.cleaned_data)
        data_root().repositories.append(repository)
        transaction.commit()
        return redirect(repository_view, repository.oid)
    return TemplateResponse(request, 'core/repository/add.html', {
        'repository_form': repository_form,
    })


def repository_check_config_add(request, repository_id):
    repository = Repository.oid_get(repository_id)
    data = request.POST or None
    config_form = CheckConfig.Form(data)
    if data and config_form.is_valid():
        config = CheckConfig(repository, **config_form.cleaned_data)
        repository.job_configs.append(config)
        transaction.commit()
        return redirect(repository_view, repository.oid)
    return TemplateResponse(request, 'core/repository/config_add.html', {
        'form': config_form,
    })


def repository_check_config_edit(request, repository_id, config_id):
    repository = Repository.oid_get(repository_id)
    check_config = find_oid_or_404(repository.job_configs, config_id)
    data = request.POST or None
    check_config._p_activate()
    config_form = check_config.Form(data, initial=check_config.__dict__)
    if data and config_form.is_valid():
        check_config._update(config_form.cleaned_data)
        transaction.commit()
        return redirect(repository_view, repository_id)
    return TemplateResponse(request, 'core/repository/config_edit.html', {
        'form': config_form,
    })


def repository_check_config_delete(request, repository_id, config_id):
    repository = Repository.oid_get(repository_id)
    check_config = find_oid_or_404(repository.job_configs, config_id)
    if request.method == 'POST':
        repository.job_configs.remove(check_config)
        transaction.commit()
    return redirect(repository_view, repository_id)


def repository_check_config_trigger(request, repository_id, config_id):
    repository = Repository.oid_get(repository_id)
    check_config = find_oid_or_404(repository.job_configs, config_id)
    if request.method == 'POST':
        daemon = APIClient()
        job = daemon.initiate_check_job(check_config)
    return redirect(repository_view, repository_id)


from dateutil.relativedelta import relativedelta


def schedules(request):
    this_month = now().replace(day=1, hour=0, minute=0, second=0)
    end_of_this_month = this_month + relativedelta(months=1)

    schedules = data_root().schedules
    for schedule in schedules:
        schedule.occurences = schedule.recurrence.between(this_month, end_of_this_month, dtstart=schedule.recurrence_start)
    return TemplateResponse(request, 'core/schedule/schedule.html', {
        'schedules': schedules,
    })


def schedule_add_and_edit(request, data, schedule=None, context=None):
    if schedule:
        schedule._p_activate()
        form = Schedule.Form(data, initial=schedule.__dict__)
    else:
        form = Schedule.Form(data)
    action_forms = []

    # This generally works since pluggy loads plugin modules for us.
    classes = ScheduledAction.__subclasses__()
    log.debug('Discovered schedulable actions: %s', ', '.join(cls.dotted_path() for cls in classes))

    if schedule:
        for scheduled_action in schedule.actions:
            scheduled_action._p_activate()
            action_form = scheduled_action.form(initial=scheduled_action.__dict__)
            action_forms.append(action_form)

    if data:
        actions_data = json.loads(data['actions-data'])

        all_valid = form.is_valid()

        class AbortTransaction(Exception):
            pass

        try:
            with transaction.manager:
                if all_valid:
                    if schedule:
                        schedule.actions.clear()
                        schedule._update(form.cleaned_data)
                    else:
                        schedule = Schedule(**form.cleaned_data)
                        data_root().schedules.append(schedule)

                for serialized_action in actions_data:
                    dotted_path = serialized_action.pop('class')
                    if not ScheduledAction.valid_class(dotted_path):
                        log.error('invalid/unknown schedulable action %r, ignoring', dotted_path)
                        continue
                    action = import_string(dotted_path)
                    action_form = action.form(serialized_action)

                    valid = action_form.is_valid()
                    all_valid &= valid
                    if all_valid:
                        scheduled_action = action(schedule, **action_form.cleaned_data)
                        schedule.actions.append(scheduled_action)
                    action_forms.append(action_form)

                if not all_valid:
                    raise AbortTransaction
                return redirect(schedules)
        except AbortTransaction:
            pass
    context = dict(context or {})
    context.update({
        'form': form,
        'classes': {cls.dotted_path(): cls.name for cls in classes},
        'action_forms': action_forms,
    })
    return TemplateResponse(request, 'core/schedule/add.html', context)


def schedule_add(request):
    data = request.POST or None
    return schedule_add_and_edit(request, data, context={
        'title': _('Add schedule'),
        'submit': _('Add schedule'),
    })


def schedule_edit(request, schedule_id):
    for schedule in data_root().schedules:
        if schedule.oid == schedule_id:
            break
    else:
        raise Http404
    data = request.POST or None
    return schedule_add_and_edit(request, data, schedule, context={
        'title': _('Edit schedule {}').format(schedule.name),
        'submit': _('Save changes'),
        'schedule': schedule,
    })


def schedule_delete(request, schedule_id):
    for schedule in data_root().schedules:
        if schedule.oid == schedule_id:
            break
    else:
        raise Http404
    if request.method == 'POST':
        data_root().schedules.remove(schedule)
        transaction.commit()
    return redirect(schedules)


def scheduled_action_form(request):
    dotted_path = request.GET.get('class')
    if not ScheduledAction.valid_class(dotted_path):
        log.error('scheduled_action_form request for %r which is not a schedulable action', dotted_path)
        return HttpResponseBadRequest()
    try:
        cls = import_string(dotted_path)
    except ImportError:
        log.error('scheduled_action_form: failed to import %r', dotted_path)
        return HttpResponseBadRequest()
    return HttpResponse(cls.Form().as_table())


def schedule_list(request):
    return TemplateResponse(request, 'core/schedule/list.html', {
        'm': Schedule,
        'schedules': data_root().schedules,
    })
