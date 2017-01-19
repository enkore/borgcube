
from borgcube.vendor import pluggy

hookspec = pluggy.HookspecMarker('borgcube')


@hookspec(firstresult=True)
def borgcube_web_get_url(obj):
    """
    Return URL for *obj* or None.
    """


@hookspec
def borgcube_web_children(publisher, children):
    """

    """


@hookspec
def borgcube_web_jinja_env(env):
    """
    """
    # TODO what about Environment options? do we even *want* to expose those?
