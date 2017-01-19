
import transaction

from django.utils.translation import ugettext_lazy as _

from .management import ManagementPublisher

from borgcube.job.prune import prune_root, RetentionPolicy, PruneConfig


class PrunePublisher(ManagementPublisher):
    companion = 'pr'
    menu_text = _('Pruning')

    def children(self):
        return self.children_hook({
            'policies': PoliciesPublisher(self.pr.policies),
            'configs': ConfigsPublisher(self.pr.configs),
        })

    def base_template(self, request):
        return 'core/prune/intro.html'

    view = ManagementPublisher.render


class PoliciesPublisher(ManagementPublisher):
    companion = 'policies'
    views = ('add', )
    menu_text = _('Retention policies')

    def children(self):
        return self.children_hook({policy.oid: PolicyPublisher(policy) for policy in self.policies})

    def view(self, request):
        return self.render(request, 'core/prune/retention.html')

    def add_view(self, request):
        data = request.POST or None
        form = RetentionPolicy.Form(data)
        if data and form.is_valid():
            policy = RetentionPolicy(**form.cleaned_data)
            prune_root().policies.append(policy)
            transaction.get().note('Added prune retention policy %s' % policy.name)
            transaction.commit()
            # return redirect(prune_retention_policies)
        return self.render(request, 'core/prune/policy_add.html', {
            'form': form,
            'title': _('Add retention policy'),
            'submit': _('Add retention policy'),
        })


class PolicyPublisher(ManagementPublisher):
    companion = 'policy'
    views = ('delete', )

    def view(self, request):
        data = request.POST or None
        self.policy._p_activate()
        form = RetentionPolicy.Form(data, initial=self.policy.__dict__)
        if data and form.is_valid():
            self.policy._update(form.cleaned_data)
            transaction.get().note('Edited prune retention policy %s' % self.policy.oid)
            transaction.commit()
            return self.parent.redirect_to()
        return self.render(request, 'core/prune/policy_add.html', {
            'form': form,
            'title': _('Edit retention policy'),
            'submit': _('Save changes'),
        })

    def delete_view(self, request):
        policies = self.parent.policies
        if request.method == 'POST':
            policies.remove(self.policy)
            transaction.get().note('Deleted policy %s' % self.policy.oid)
            transaction.commit()
        return self.parent.redirect_to()


class ConfigsPublisher(ManagementPublisher):
    companion = 'configs'
    views = ('add', )
    menu_text = _('Configurations')

    def children(self):
        return self.children_hook({config.oid: ConfigPublisher(config) for config in self.configs})

    def view(self, request):
        return self.render(request, 'core/prune/configs.html')

    def add_view(self, request):
        data = request.POST or None
        form = PruneConfig.Form(data)
        if data and form.is_valid():
            config = PruneConfig(**form.cleaned_data)
            prune_root().configs.append(config)
            transaction.get().note('Added prune config %s' % config.name)
            transaction.commit()
            return self.redirect_to()
        return self.render(request, 'core/prune/config_add.html', {
            'form': form,
            'title': _('Add prune configuration'),
            'submit': _('Add prune configuration'),
        })


class ConfigPublisher(ManagementPublisher):
    companion = 'config'
    views = ('preview', 'trigger', 'delete', )

    def view(self, request):
        data = request.POST or None
        form = PruneConfig.Form(data, initial=self.config.__dict__)
        if data and form.is_valid():
            self.config._update(form.cleaned_data)
            transaction.get().note('Edited prune config %s' % self.config.oid)
            transaction.commit()
            return self.parent.redirect_to()
        return self.render(request, 'core/prune/config_add.html', {
            'form': form,
            'title': _('Edit prune configuration'),
            'submit': _('Edit prune configuration'),
        })

    def preview_view(self, request):
        archives = self.config.apply_policy(keep_mark=True)
        return self.render(request, 'core/prune/preview.html', {
            'archives': archives,
        })

    def trigger_view(self, request):
        if request.method == 'POST':
            job = self.config.create_job()
            transaction.commit()
        return self.parent.redirect_to()

    def delete_view(self, request):
        if request.method == 'POST':
            self.parent.configs.remove(self.config)
            transaction.commit()
        return self.parent.redirect_to()


def borgcube_web_children(publisher, children):
    if publisher.name == 'management':
        return {
            'prune': PrunePublisher(prune_root()),
        }
