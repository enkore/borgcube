
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

from .views import Publisher, PublisherMenu
from borgcube.job.prune import prune_root, RetentionPolicy


class PrunePublisher(Publisher, PublisherMenu):
    companion = 'pr'
    menu_descend = True
    menu_title = ugettext_lazy('Pruning')

    def children(self):
        return {
            'policies': PoliciesPublisher(self.pr.policies, self),
#            'configs': ConfigsPublisher(self.pr.configs, self),
        }

    def view(self, request):
        return TemplateResponse(request, 'core/prune/intro.html', {
            'management': True,
        })


class PoliciesPublisher(Publisher, PublisherMenu):
    companion = 'policies'
    views = ('add', )
    menu_descend = False
    menu_title = ugettext_lazy('Retention policies')

    def children(self):
        return {policy.oid: PolicyPublisher(policy, self) for policy in self.policies}

    def view(self, request):
        return TemplateResponse(request, 'core/prune/retention.html', {
            'policies': self.policies,
            'management': True,
        })

    def add_view(self, request):
        data = request.POST or None
        form = RetentionPolicy.Form(data)
        if data and form.is_valid():
            policy = RetentionPolicy(**form.cleaned_data)
            prune_root().policies.append(policy)
            transaction.get().note('Added prune retention policy %s' % policy.name)
            transaction.commit()
            # return redirect(prune_retention_policies)
        return TemplateResponse(request, 'core/prune/policy_add.html', {
            'form': form,
            'title': _('Add retention policy'),
            'submit': _('Add retention policy'),
            'management': True,
        })


class PolicyPublisher(Publisher):
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
            return redirect(prune_retention_policies)
        return TemplateResponse(request, 'core/prune/policy_add.html', {
            'form': form,
            'title': _('Edit retention policy'),
            'submit': _('Save changes'),
            'management': True,
        })

    def delete_view(self, request):
        policies = self.parent.policies
        if request.method == 'POST':
            policies.remove(self.policy)
            transaction.get().note('Deleted policy %s' % self.policy.oid)
            transaction.commit()
        return redirect(prune_retention_policies)

"""
def prune_configs(request):
    configs = prune_root().configs
    return TemplateResponse(request, 'core/prune/configs.html', {
        'configs': configs,
        'management': True,
    })


def prune_config_add(request):
    data = request.POST or None
    form = PruneConfig.Form(data)
    if data and form.is_valid():
        config = PruneConfig(**form.cleaned_data)
        prune_root().configs.append(config)
        transaction.get().note('Added prune config %s' % config.name)
        transaction.commit()
        return redirect(prune_configs)
    return TemplateResponse(request, 'core/prune/config_add.html', {
        'form': form,
        'title': _('Add prune configuration'),
        'submit': _('Add prune configuration'),
        'management': True,
    })


def prune_config_edit(request, config_id):
    config = find_oid_or_404(prune_root().configs, config_id)
    config._p_activate()
    data = request.POST or None
    form = PruneConfig.Form(data, initial=config.__dict__)
    if data and form.is_valid():
        config._update(form.cleaned_data)
        transaction.get().note('Edited prune config %s' % config.oid)
        transaction.commit()
        return redirect(prune_configs)
    return TemplateResponse(request, 'core/prune/config_add.html', {
        'form': form,
        'title': _('Edit prune configuration'),
        'submit': _('Edit prune configuration'),
        'management': True,
    })


def prune_config_preview(request, config_id):
    config = find_oid_or_404(prune_root().configs, config_id)
    archives = config.apply_policy(keep_mark=True)
    return TemplateResponse(request, 'core/prune/preview.html', {
        'config': config,
        'archives': archives,
        'management': True,
    })


def prune_config_trigger(request, config_id):
    config = find_oid_or_404(prune_root().configs, config_id)
    if request.method == 'POST':
        job = config.create_job()
        transaction.commit()
    return redirect(prune_configs)


def prune_config_delete(request, config_id):
    config = find_oid_or_404(prune_root().configs, config_id)
"""


def borgcube_web_publish(publisher, segment):
    if publisher.name == 'management' and segment == 'prune':
        return PrunePublisher(prune_root())
