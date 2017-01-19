
import transaction
from borgcube.job.backup import BackupConfig

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django import forms
from django.utils.translation import ugettext_lazy as _

from borgcube.core.models import Client, RshClientConnection, Repository
from borgcube.utils import data_root, find_oid
from . import Publisher


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


class ClientsPublisher(Publisher):
    companion = 'clients'
    views = ('add',)

    def __getitem__(self, hostname):
        client = self.clients[hostname]
        return ClientPublisher(client)

    def view(self, request):
        return self.render(request, 'core/client/list.html', {
            'm': Client,
            'clients': self.clients.values(),
        })

    def add_view(self, request):
        data = request.POST or None
        client_form = Client.Form(data)
        connection_form = RshClientConnection.Form(data)
        if data and client_form.is_valid() and connection_form.is_valid():
            connection = RshClientConnection(**connection_form.cleaned_data)
            client = Client(connection=connection, **client_form.cleaned_data)
            transaction.get().note('Added client %s' % client.hostname)
            transaction.commit()
            return self.redirect_to()
        return self.render(request, 'core/client/add.html', {
            'client_form': client_form,
            'connection_form': connection_form,
        })


class ClientPublisher(Publisher):
    companion = 'client'
    views = ('edit', )

    def children(self):
        return self.children_hook({
            'job-configs': JobConfigsPublisher(self.client.job_configs),
        })

    def view(self, request):
        jobs = paginate(request, self.client.jobs.values(), prefix='jobs')
        return self.render(request, 'core/client/view.html', {
            'client': self.client,
            'jobs': jobs,
        })

    def edit_view(self, request):
        client = self.client
        data = request.POST or None
        client.connection._p_activate()
        client_form = Client.Form(data, initial=client.__dict__)
        del client_form.fields['hostname']
        connection_form = RshClientConnection.Form(data, initial=client.connection.__dict__)
        if data and client_form.is_valid() and connection_form.is_valid():
            client._update(client_form.cleaned_data)
            client.connection._update(connection_form.cleaned_data)
            transaction.get().note('Edited client %s' % client.hostname)
            transaction.commit()
            return self.redirect_to()
        return self.render(request, 'core/client/edit.html', {
            'client': client,
            'client_form': client_form,
            'connection_form': connection_form,
        })


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


class JobConfigsPublisher(Publisher):
    companion = 'configs'
    views = ('add', )

    def __getitem__(self, oid):
        return JobConfigPublisher(find_oid(self.configs, oid))

    def add_view(self, request):
        client = self.parent.client
        data = request.POST or None
        form = JobConfigForm(data=data)
        advanced_form = JobConfigForm.AdvancedForm(data=data)
        if data and form.is_valid() and advanced_form.is_valid():
            config = form.cleaned_data
            config.update(advanced_form.cleaned_data)
            config['paths'] = config.get('paths', '').split('\n')
            config['excludes'] = [s for s in config.get('excludes', '').split('\n') if s]

            repository = config.pop('repository')
            job_config = BackupConfig(client=client, repository=repository, label=config['label'])
            job_config._update(config)
            client.job_configs.append(job_config)

            transaction.get().note('Added job config to client %s' % client.hostname)
            transaction.commit()

            # TODO StringListValidator
            # TODO Pattern validation
            # TODO fancy pattern editor with test area

            return self[job_config.oid].redirect_to()
        return self.render(request, 'core/client/config_add.html', {
            'form': form,
            'advanced_form': advanced_form,
        })


class JobConfigPublisher(Publisher):
    companion = 'config'
    views = ('edit', 'delete', 'trigger', )

    def reverse(self, view=None):
        if view:
            return super().reverse(view)
        else:
            return self.parent.parent.reverse() + '#job-config-' + self.config.oid

    def edit_view(self, request):
        client = self.config.client
        job_config = self.config
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

            transaction.get().note('Edited job config %s of client %s' % (job_config.oid, client.hostname))
            transaction.commit()

            return self.redirect_to()
        return self.render(request, 'core/client/config_edit.html', {
            'client': client,
            'form': form,
            'advanced_form': advanced_form,
            'job_config': job_config,
        })

    def delete_view(self, request):
        client = self.parent.parent.client
        if request.method == 'POST':
            client.job_configs.remove(self.config)
            # Could just leave it there, but likely not the intention behind clicking (delete).
            for schedule in data_root().schedules:
                for action in list(schedule.actions):
                    if getattr(action, 'job_config', None) == self.config:
                        schedule.actions.remove(action)
            transaction.get().note('Deleted job config %s from client %s' % (self.config.oid, client.hostname))
            transaction.commit()
        return self.redirect_to()

    def trigger_view(self, request):
        if request.method == 'POST':
            job = self.config.create_job()
            transaction.commit()
        return self.redirect_to()
