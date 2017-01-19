import logging
import itertools

from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import redirect, get_object_or_404
from borgcube.core.models import Job
from borgcube.daemon.client import APIClient
from borgcube.utils import data_root

from ..metrics import WebData

from . import Publisher
from .client import ClientsPublisher
from .schedule import SchedulesPublisher
from .repository import RepositoriesPublisher
from .management import ManagementAreaPublisher

log = logging.getLogger(__name__)


def job_view(request, job_id):
    job = get_object_or_404(Job, id=job_id)


def job_cancel(request, job_id):
    job = data_root().jobs[int(job_id)]
    daemon = APIClient()
    daemon.cancel_job(job)
    return redirect(client_view, job.client.hostname)


class RootPublisher(Publisher):
    companion = 'dr'
    views = ()

    def children(self):
        return self.children_hook({
            'clients': ClientsPublisher(self.dr.clients),
            'schedules': SchedulesPublisher(self.dr.schedules),
            'repositories': RepositoriesPublisher(self.dr.repositories),
            'management': ManagementAreaPublisher(self.dr.ext),
        })

    def view(self, request):
        recent_jobs = itertools.islice(reversed(self.dr.jobs), 20)
        return self.render(request, 'core/dashboard.html', {
            'metrics': self.dr.plugin_data(WebData).metrics,
            'recent_jobs': recent_jobs,
        })

    def reverse(self, view=None):
        return '/'


def object_publisher(request, path):
    """
    Renders a *path* against the *RootPublisher*.

    The request will receive the following attributes:

    - *publisher*: the publisher handling the request
    - *view_name*: the verbatim view name (?view=...)
    """
    view_name = request.GET.get('view')
    path_segments = [s for s in path.split('/') if s != '.']
    path_segments.reverse()

    if '..' in path_segments:
        log.warning('Bad request: Refusing path containing "..".')
        return HttpResponse(status=400)

    root_publisher = RootPublisher(data_root())
    view = root_publisher.resolve(path_segments, view_name)

    try:
        request.root = root_publisher
        request.publisher = view.__self__
        request.view_name = view_name
    except AttributeError:
        # We don't explicitly prohibit the resolver to return a view callable that isn't
        # part of a publisher.
        pass
    response = view(request)
    if response is None:
        qualname = view.__module__ + '.' + view.__qualname__
        raise ValueError('The view %s returned None instead of a HTTPResponse' % qualname)
    return response
