
from borgcube.vendor import pluggy

hookspec = pluggy.HookspecMarker('borgcube')


@hookspec
def borgcube_web_metrics():
    """
    Return list of metric (borgcube.web.metrics.Metric) implementations.
    """


@hookspec
def borgcube_web_urlpatterns(urlpatterns):
    """
    Called once at setup time with the root *urlpatterns*.
    """


@hookspec(firstresult=True)
def borgcube_web_job_outcome(job):
    """
    Return human-compatible outcome description of *job* or None.
    """
