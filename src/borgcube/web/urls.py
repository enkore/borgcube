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
from django.contrib import admin

from .core import views as core_views
from borgcube.utils import hook

client_urls = [
    url(r'^$', core_views.client_view, name='core.client_view'),
    url(r'^edit/$', core_views.client_edit, name='core.client_edit'),
    url(r'^add-config/$', core_views.job_config_add, name='core.job_config_add'),
    url(r'^config/(?P<config_id>\d+)/edit/$', core_views.job_config_edit, name='core.job_config_edit'),
    url(r'^config/(?P<config_id>\d+)/delete/$', core_views.job_config_delete, name='core.job_config_delete'),
    url(r'^config/(?P<config_id>\d+)/trigger/$', core_views.job_config_trigger, name='core.job_config_trigger'),
]

repo_urls = [
    url(r'^$', core_views.repository_view, name='core.repository_view'),
    url(r'^edit/$', core_views.repository_edit, name='core.repository_edit'),
    url(r'^add-config/$', core_views.repository_check_config_add, name='core.repository_check_config_add'),
    url(r'^config/(?P<config_id>\d+)/edit/$', core_views.repository_check_config_edit, name='core.repository_check_config_edit'),
    url(r'^config/(?P<config_id>\d+)/delete/$', core_views.repository_check_config_delete, name='core.repository_check_config_delete'),
    url(r'^config/(?P<config_id>\d+)/trigger/$', core_views.repository_check_config_trigger, name='core.repository_check_config_trigger'),
]

job_urls = [
    url(r'^(?P<job_id>\d+)/$', core_views.job_view, name='core.job_view'),
    url(r'^(?P<job_id>\d+)/cancel/$', core_views.job_cancel, name='core.job_cancel'),
]

urlpatterns = [
    url(r'^$', core_views.dashboard, name='core.dashboard'),
    url(r'^clients/$', core_views.clients, name='core.clients'),
    url(r'^clients/add/$', core_views.client_add, name='core.client_add'),
    url(r'^clients/id/(?P<client_id>[-.\w]+)/', include(client_urls)),

    url(r'^repositories/$', core_views.repositories, name='core.repositories'),
    url(r'^repositories/add/$', core_views.repository_add, name='core.repository_add'),
    url(r'^repositories/(?P<id>\d+)/', include(repo_urls)),

    url(r'^job/', include(job_urls)),

    url(r'^admin/', admin.site.urls),
]

hook.borgcube_web_urlpatterns(urlpatterns=urlpatterns)
