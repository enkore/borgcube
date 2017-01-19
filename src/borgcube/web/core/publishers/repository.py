import transaction

from borgcube.core.models import Repository
from borgcube.job.check import CheckConfig
from borgcube.utils import data_root, find_oid
from . import Publisher


class RepositoriesPublisher(Publisher):
    companion = 'repositories'
    views = ('add', )

    def __getitem__(self, repository_id):
        repository = Repository.oid_get(repository_id)
        return RepositoryPublisher(repository, self)

    def view(self, request):
        return self.render(request, 'core/repository/list.html', {
            'm': Repository,
        })

    def add_view(self, request):
        data = request.POST or None
        repository_form = Repository.Form(data)
        if data and repository_form.is_valid():
            repository = Repository(**repository_form.cleaned_data)
            data_root().repositories.append(repository)
            transaction.get().note('Added repository %s' % repository.name)
            transaction.commit()
            return self.redirect_to()
        return self.render(request, 'core/repository/add.html', {
            'repository_form': repository_form,
        })


class RepositoryPublisher(Publisher):
    companion = 'repository'
    views = ('edit', )

    def children(self):
        return self.children_hook({
            'check-configs': RepositoryCheckConfigsPublisher(self.repository, self),
        })

    def view(self, request):
        return self.render(request, 'core/repository/view.html')

    def edit_view(self, request):
        data = request.POST or None
        repository = self.repository
        repository._p_activate()
        repository_form = Repository.Form(data, initial=repository.__dict__)
        if data and repository_form.is_valid():
            repository._update(repository_form.cleaned_data)
            transaction.get().note('Edited repository %s' % repository.oid)
            transaction.commit()
            return self.redirect_to()
        return self.render(request, 'core/repository/edit.html', {
            'repository_form': repository_form,
        })


class RepositoryCheckConfigsPublisher(Publisher):
    companion = 'repository'
    views = ('add', )

    def __getitem__(self, config_id):
        config = find_oid(self.repository.job_configs, config_id)
        return RepositoryCheckConfigPublisher(config, self)

    def add_view(self, request):
        data = request.POST or None
        config_form = CheckConfig.Form(data)
        if data and config_form.is_valid():
            config = CheckConfig(self.repository, **config_form.cleaned_data)
            self.repository.job_configs.append(config)
            transaction.get().note('Added check config to repository %s' % self.repository.oid)
            transaction.commit()
            return self.parent.redirect_to()
        return self.render(request, 'core/repository/config_add.html', {
            'form': config_form,
        })


class RepositoryCheckConfigPublisher(Publisher):
    companion = 'config'
    views = ('edit', 'delete', 'trigger', )

    def edit_view(self, request):
        check_config = self.config
        data = request.POST or None
        check_config._p_activate()
        config_form = check_config.Form(data, initial=check_config.__dict__)
        if data and config_form.is_valid():
            check_config._update(config_form.cleaned_data)
            transaction.get().note('Edited check config %s on repository %s' % (check_config.oid, self.parent.repository.oid))
            transaction.commit()
            return self.parent.parent.redirect_to()
        return self.render(request, 'core/repository/config_edit.html', {
            'form': config_form,
        })

    def delete_view(self, request):
        if request.method == 'POST':
            repository = self.parent.repository
            repository.job_configs.remove(self.config)
            transaction.get().note('Deleted check config %s from repository %s' % (self.config.oid, repository.oid))
            transaction.commit()
        return self.parent.parent.redirect_to()

    def trigger_view(self, request):
        if request.method == 'POST':
            job = self.config.create_job()
            transaction.commit()
        return self.parent.parent.redirect_to()
