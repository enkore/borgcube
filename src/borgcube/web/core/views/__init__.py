import logging

from django import forms
from django.shortcuts import redirect, get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.module_loading import import_string
from django.utils.translation import ugettext_lazy as _

from ..models import OverviewMetric
from ..metrics import Metric

from borgcube.core.models import Client, ClientConnection, Repository, CheckConfig
from borgcube.core.models import Job, JobConfig
from borgcube.daemon.client import APIClient

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
    return TemplateResponse(request, 'core/dashboard.html', {
        'metrics': fetch_metrics(),
        'recent_jobs': Job.objects.all()[:20],
    })


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = '__all__'
        exclude =('connection',)


class ClientConnectionForm(forms.ModelForm):
    prefix = 'connection'

    class Meta:
        model = ClientConnection
        fields = '__all__'


def clients(request):
    # TODO this makes one extra query per client due to latest_job
    clients = Client.objects.all().order_by('hostname')
    return TemplateResponse(request, 'core/client/list.html', {
        'm': Client,
        'clients': clients,
    })


def client_view(request, client_id):
    client = get_object_or_404(Client, pk=client_id)
    return TemplateResponse(request, 'core/client/view.html', {
        'client': client,
    })


def client_add(request):
    data = request.POST or None
    client_form = ClientForm(data)
    connection_form = ClientConnectionForm(data)
    if data and client_form.is_valid() and connection_form.is_valid():
        connection = connection_form.save()
        created_client = client_form.save(commit=False)
        created_client.connection = connection
        created_client.save()
        return redirect(client_view, created_client.pk)
    return TemplateResponse(request, 'core/client/add.html', {
        'client_form': client_form,
        'connection_form': connection_form,
    })


def client_edit(request, client_id):
    client = get_object_or_404(Client, pk=client_id)
    data = request.POST or None
    client_form = ClientForm(data, instance=client)
    del client_form.fields['hostname']
    connection_form = ClientConnectionForm(data, instance=client.connection)
    if data and client_form.is_valid() and connection_form.is_valid():
        connection_form.save()
        client_form.save()
        return redirect(client_view, client.pk)
    return TemplateResponse(request, 'core/client/edit.html', {
        'client': client,
        'client_form': client_form,
        'connection_form': connection_form,
    })


def job_view(request, job_id):
    job = get_object_or_404(Job, id=job_id)


def job_cancel(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    daemon = APIClient()
    daemon.cancel_job(job)
    return redirect(client_view, job.client.pk)


class JobConfigForm(forms.Form):
    COMPRESSION_CHOICES = [
        ('none', _('No compression')),
        ('lz4', _('LZ4 (fast)')),
    ] \
        + [('zlib,%d' % level, _('zlib level %d') % level) for level in range(1, 10)] \
        + [('lzma,%d' % level, _('LZMA level %d') % level) for level in range(1, 7)]

    label = forms.CharField()

    repository = forms.ModelChoiceField(Repository.objects.all())

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
    client = get_object_or_404(Client, pk=client_id)
    data = request.POST or None
    form = JobConfigForm(data=data)
    advanced_form = JobConfigForm.AdvancedForm(data=data)
    if data and form.is_valid() and advanced_form.is_valid():
        config = form.cleaned_data
        config.update(advanced_form.cleaned_data)
        repository = config.pop('repository')
        config['version'] = 1
        # TODO StringListValidator
        # TODO Pattern validation
        # TODO fancy pattern editor with test area
        config['paths'] = config.get('paths', '').split('\n')
        config['excludes'] = [s for s in config.get('excludes', '').split('\n') if s]
        job_config = JobConfig(client=client, config=config, repository=repository)
        job_config.save()
        return redirect(reverse(client_view, args=[client.pk]) + '#jobconfig-%d' % job_config.id)
    return TemplateResponse(request, 'core/client/config_add.html', {
        'form': form,
        'advanced_form': advanced_form,
    })


def job_config_edit(request, client_id, config_id):
    job_config = get_object_or_404(JobConfig, client=client_id, id=config_id)
    data = request.POST or None
    initial_data = dict(job_config.config)
    initial_data['paths'] = '\n'.join(initial_data['paths'])
    initial_data['excludes'] = '\n'.join(initial_data['excludes'])
    initial_data['repository'] = job_config.repository
    form = JobConfigForm(data=data, initial=initial_data)
    advanced_form = JobConfigForm.AdvancedForm(data=data, initial=initial_data)
    if data and form.is_valid() and advanced_form.is_valid():
        config = form.cleaned_data
        config.update(advanced_form.cleaned_data)
        repository = config.pop('repository')
        config['version'] = 1
        # TODO StringListValidator
        # TODO Pattern validation
        # TODO fancy pattern editor with test area
        config['paths'] = config.get('paths', '').split('\n')
        config['excludes'] = [s for s in config.get('excludes', '').split('\n') if s]

        job_config.repository = repository
        job_config.config = config
        job_config.save()
        return redirect(reverse(client_view, args=[job_config.client.pk]) + '#jobconfig-%d' % job_config.id)
    return TemplateResponse(request, 'core/client/config_edit.html', {
        'form': form,
        'advanced_form': advanced_form,
        'job_config': job_config,
    })


def job_config_delete(request, client_id, config_id):
    config = get_object_or_404(JobConfig, client=client_id, id=config_id)
    if request.method == 'POST':
        config.delete()
    return redirect(client_view, client_id)


def job_config_trigger(request, client_id, config_id):
    client = get_object_or_404(Client, pk=client_id)
    config = get_object_or_404(JobConfig, client=client_id, id=config_id)
    daemon = APIClient()
    job = daemon.initiate_backup_job(client, config)
    return redirect(client_view, client_id)


class RepositoryForm(forms.ModelForm):
    # TODO update repo id during connection check
    class Meta:
        model = Repository
        fields = '__all__'


def repositories(request):
    return TemplateResponse(request, 'core/repository/list.html', {
        'm': Repository,
        'repositories': Repository.objects.all(),
    })


def repository_view(request, id):
    repository = get_object_or_404(Repository, id=id)
    return TemplateResponse(request, 'core/repository/view.html', {
        'repository': repository,
    })


def repository_edit(request, id):
    repository = get_object_or_404(Repository, pk=id)
    data = request.POST or None
    repository_form = RepositoryForm(data, instance=repository)
    if data and repository_form.is_valid():
        repository_form.save()
        return redirect(repository_view, repository.pk)
    return TemplateResponse(request, 'core/repository/edit.html', {
        'repository': repository,
        'repository_form': repository_form,
    })


def repository_add(request):
    data = request.POST or None
    repository_form = RepositoryForm(data)
    if data and repository_form.is_valid():
        repository = repository_form.save()
        return redirect(repository_view, repository.pk)
    return TemplateResponse(request, 'core/repository/add.html', {
        'repository_form': repository_form,
    })


class CheckConfigForm(forms.ModelForm):
    class Meta:
        model = CheckConfig
        fields = '__all__'
        exclude =('repository',)


def repository_check_config_add(request, id):
    repository = get_object_or_404(Repository, pk=id)
    data = request.POST or None
    config_form = CheckConfigForm(data)
    if data and config_form.is_valid():
        check_config = config_form.save(commit=False)
        check_config.repository = repository
        check_config.save()
        return redirect(repository_view, repository.pk)
    return TemplateResponse(request, 'core/repository/config_add.html', {
        'form': config_form,
    })


def repository_check_config_edit(request, id, config_id):
    check_config = get_object_or_404(CheckConfig, repository=id, pk=config_id)
    data = request.POST or None
    config_form = CheckConfigForm(data, instance=check_config)
    if data and config_form.is_valid():
        config_form.save()
        return redirect(repository_view, id)
    return TemplateResponse(request, 'core/repository/config_edit.html', {
        'form': config_form,
    })


def repository_check_config_delete(request, id, config_id):
    config = get_object_or_404(CheckConfig, repository=id, id=config_id)
    if request.method == 'POST':
        config.delete()
    return redirect(repository_view, id)


def repository_check_config_trigger(request, id, config_id):
    config = get_object_or_404(CheckConfig, repository=id, id=config_id)
    daemon = APIClient()
    job = daemon.initiate_check_job(config)
    return redirect(repository_view, id)
