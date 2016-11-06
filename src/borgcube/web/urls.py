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


client_urls = [
    url(r'^$', core_views.client_view, name='core.client_view'),
    url(r'^edit/$', core_views.client_edit, name='core.client_edit'),
    url(r'^add-config/$', core_views.job_config_add, name='core.job_config_add'),
    url(r'^config/(?P<config_id>\d+)/edit/$', core_views.job_config_edit, name='core.job_config_edit'),
    url(r'^config/(?P<config_id>\d+)/delete/$', core_views.job_config_delete, name='core.job_config_delete'),
    url(r'^config/(?P<config_id>\d+)/trigger/$', core_views.job_config_trigger, name='core.job_config_trigger'),
    url(r'^job/(?P<job_id>[-\w]+)/$', core_views.job_view, name='core.job_view'),
]

urlpatterns = [
    url(r'^$', core_views.dashboard, name='core.dashboard'),
    url(r'^clients/$', core_views.clients, name='core.clients'),
    url(r'^clients/add/$', core_views.client_add, name='core.client_add'),
    url(r'^clients/id/(?P<client_id>[-.\w]+)/', include(client_urls)),

    url(r'^admin/', admin.site.urls),
]

import django.core.management.commands.runserver