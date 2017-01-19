
from borgcube.vendor import pluggy

hookspec = pluggy.HookspecMarker('borgcube')


@hookspec(firstresult=True)
def borgcube_web_job_outcome(job):
    """
    Return human-compatible outcome description of *job* or None.
    """


@hookspec(firstresult=True)
def borgcube_web_get_url(obj):
    """
    Return URL for *obj* or None.
    """


@hookspec
def borgcube_web_management_nav(nav):
    """
    Insert menu item dicts into *nav*::

        {
            'view': 'callable or name',
            'url': 'url (str). only give either view or url',
            'text': 'translated link text (possibly lazy)',
            'items': [
                # Optional list of child menu items.
            ],
        }
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
