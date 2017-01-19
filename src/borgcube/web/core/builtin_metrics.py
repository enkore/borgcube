
import logging

import transaction

from django.utils.translation import pgettext_lazy as _, ugettext_lazy
from django.utils import timezone

from borg.helpers import format_file_size

from borgcube.core.models import Job, NumberTree
from borgcube.utils import data_root

from .metrics import Metric
from . import views

log = logging.getLogger(__name__)


class ArchiveCount(Metric):
    name = _('ArchiveCount metric name', 'Number of archives')
    label = _('ArchiveCount metric label', 'archives')

    def formatted_value(self):
        return str(len(data_root().archives))


class TotalData(Metric):
    name = _('TotalData metric name', 'Total amount of data in repositories')
    label = _('TotalData metric label', '(total data)')

    def formatted_value(self):
        total_size = 0
        for archive in data_root().archives.values():
            total_size += archive.original_size
        return format_file_size(total_size)


class BackupsToday(Metric):
    name = _('BackupsToday metric name', 'Backups made today')
    label = _('BackupsToday metric label', 'backups today')

    def formatted_value(self):
        today_begin = timezone.now().replace(hour=0, minute=0, microsecond=0)
        jobs = 0
        for job in NumberTree.reversed(data_root().jobs_by_state[Job.State.done]):
            if job.created < today_begin:
                break
            jobs += 1
        transaction.abort()
        return str(jobs)


def borgcube_web_management_nav(nav):
    nav.append({
        'view': views.prune,
        'text': ugettext_lazy('Pruning'),
        'items': [
            {
                'view': views.prune_retention_policies,
                'text': ugettext_lazy('Retention policies'),
            },
            {
                'view': views.prune_configs,
                'text': ugettext_lazy('Configurations'),
            }
        ],
    })


from django.template.response import TemplateResponse
from django.utils.translation import ugettext_lazy as _

from .views import ManagementPublisher, Publisher, PublisherMenu
from borgcube.job.prune import prune_root, RetentionPolicy, PruneConfig
from borgcube.utils import find_oid_or_404


class PrunePublisher(ManagementPublisher):
    companion = 'pr'
    menu_text = _('Pruning')

    def children(self):
        return self.children_hook({
            'policies': PoliciesPublisher(self.pr.policies),
            'configs': ConfigsPublisher(self.pr.configs, self),
        })

    def base_template(self, request):
        return 'core/prune/intro.html'

    view = ManagementPublisher.render


class PoliciesPublisher(ManagementPublisher):
    companion = 'policies'
    views = ('add', )
    menu_text = _('Retention policies')

    def children(self):
        return self.children_hook({policy.oid: PolicyPublisher(policy, self) for policy in self.policies})

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
        return self.children_hook({config.oid: ConfigPublisher(config, self) for config in self.configs})

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


#def borgcube_web_resolve(publisher, segment):
#    if publisher.name == 'management' and segment == 'prune':
#        return PrunePublisher(prune_root())

from borgcube.core.models import Trigger
from borgcube.web.core.views import ExtendingPublisher


class TriggerManagementPublisher(Publisher, PublisherMenu):
    companion = 'trigger_ids'
    menu_text = ugettext_lazy('Trigger')

    def view(self, request):
        pass


class TriggerPublisher(ExtendingPublisher):
    companion = 'trigger'
    menu_text = ugettext_lazy('Trigger')

    def view(self, request):
        return self.render(request, 'core/trigger/list.html', {})


def borgcube_web_children(publisher, children):
    if publisher.name == 'management':
        return {
            'prune': PrunePublisher(prune_root()),
            'trigger': TriggerManagementPublisher(data_root().trigger_ids),
        }
    if isinstance(getattr(publisher.get_companion(), 'trigger', None), Trigger):
        return {
            'trigger': TriggerPublisher(publisher.get_companion().trigger),
        }
