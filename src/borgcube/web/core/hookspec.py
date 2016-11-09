
from borgcube.vendor import pluggy

hookspec = pluggy.HookspecMarker('borgcube')


@hookspec
def borgcube_web_metrics():
    """
    Return list of metric (borgcube.web.metrics.Metric) implementations.
    """
