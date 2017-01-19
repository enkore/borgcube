"""web URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.10/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.conf.urls import url, include
    2. Add a URL to urlpatterns:  url(r'^blog/', include('blog.urls'))
"""
from django.conf.urls import url, include
from django.views import i18n

from .core import views as core_views
from .core.views import staticfiles
from .core.publishers.root import object_publisher
from borgcube.utils import hook
"""
client_urls = [
    url(r'^$', core_views.client_view, name='core.client_view'),
    url(r'^edit/$', core_views.client_edit, name='core.client_edit'),
    url(r'^add-config/$', core_views.job_config_add, name='core.job_config_add'),
    url(r'^config/(?P<config_id>[a-f0-9]+)/edit/$', core_views.job_config_edit, name='core.job_config_edit'),
    url(r'^config/(?P<config_id>[a-f0-9]+)/delete/$', core_views.job_config_delete, name='core.job_config_delete'),
    url(r'^config/(?P<config_id>[a-f0-9]+)/trigger/$', core_views.job_config_trigger, name='core.job_config_trigger'),
]

repo_urls = [
    url(r'^$', core_views.repository_view, name='core.repository_view'),
    url(r'^edit/$', core_views.repository_edit, name='core.repository_edit'),
    url(r'^add-config/$', core_views.repository_check_config_add, name='core.repository_check_config_add'),
    url(r'^config/(?P<config_id>[a-f0-9]+)/edit/$', core_views.repository_check_config_edit, name='core.repository_check_config_edit'),
    url(r'^config/(?P<config_id>[a-f0-9]+)/delete/$', core_views.repository_check_config_delete, name='core.repository_check_config_delete'),
    url(r'^config/(?P<config_id>[a-f0-9]+)/trigger/$', core_views.repository_check_config_trigger, name='core.repository_check_config_trigger'),
]

job_urls = [
    url(r'^(?P<job_id>[a-f0-9]+)/$', core_views.job_view, name='core.job_view'),
    url(r'^(?P<job_id>[a-f0-9]+)/cancel/$', core_views.job_cancel, name='core.job_cancel'),
]

schedule_urls = [
    url(r'^$', core_views.schedules, name='core.schedules'),
    url(r'^list/$', core_views.schedule_list, name='core.schedule_list'),
    url(r'^add/$', core_views.schedule_add, name='core.schedule_add'),
    url(r'^action-form/$', core_views.scheduled_action_form, name='core.scheduled_action_form'),
    url(r'^(?P<schedule_id>\d+)/edit/$', core_views.schedule_edit, name='core.schedule_edit'),
    url(r'^(?P<schedule_id>\d+)/delete/$', core_views.schedule_delete, name='core.schedule_delete'),
]

prune_urls = [
    url(r'^$', core_views.prune, name='prune.intro'),
    url(r'^policies/$', core_views.prune_retention_policies, name='prune.policies'),
    url(r'^policies/add/$', core_views.prune_policy_add, name='prune.policy_add'),

    url(r'^policies/(?P<policy_id>[a-f0-9]+)/edit/$', core_views.prune_policy_edit, name='prune.policy_edit'),
    url(r'^policies/(?P<policy_id>[a-f0-9]+)/delete/$', core_views.prune_policy_delete, name='prune.policy_delete'),

    url(r'^configs/$', core_views.prune_configs, name='prune.configs'),
    url(r'^configs/add/$', core_views.prune_config_add, name='prune.config_add'),
    url(r'^configs/(?P<config_id>[a-f0-9]+)/edit/$', core_views.prune_config_edit, name='prune.config_edit'),
    url(r'^configs/(?P<config_id>[a-f0-9]+)/preview/$', core_views.prune_config_preview, name='prune.config_preview'),
    url(r'^configs/(?P<config_id>[a-f0-9]+)/trigger/$', core_views.prune_config_trigger, name='prune.config_trigger'),
    url(r'^configs/(?P<config_id>[a-f0-9]+)/delete/$', core_views.prune_config_delete, name='prune.config_delete'),
]
"""

js_info_dict = {
    'packages': ('recurrence', ),
}


urlpatterns = [
    url(r'^javascript-i18n/$', i18n.javascript_catalog, js_info_dict),
    url(r'^static/(?P<file>[a-zA-Z0-9\.]+)$', staticfiles.staticfiles),

    url(r'^trigger/(?P<trigger_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/$', core_views.trigger),

    url(r'^$', object_publisher, kwargs={'path': '/'}),
    url(r'^(.*)/$', object_publisher),
]
"""
    url(r'^$', core_views.dashboard, name='core.dashboard'),
    url(r'^clients/$', core_views.clients, name='core.clients'),
    url(r'^clients/add/$', core_views.client_add, name='core.client_add'),
    url(r'^clients/id/(?P<client_id>[-.\w]+)/', include(client_urls)),

    url(r'^repositories/$', core_views.repositories, name='core.repositories'),
    url(r'^repositories/add/$', core_views.repository_add, name='core.repository_add'),
    url(r'^repositories/(?P<repository_id>[a-f0-9]+)/', include(repo_urls)),

    url(r'^job/', include(job_urls)),

    url(r'^schedules/', include(schedule_urls)),

    url(r'^management/$', core_views.management, name='core.management'),
    url(r'^management/prune/', include(prune_urls)),
]
"""

hook.borgcube_web_urlpatterns(urlpatterns=urlpatterns, js_info_dict=js_info_dict)
