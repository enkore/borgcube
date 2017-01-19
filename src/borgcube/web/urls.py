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
