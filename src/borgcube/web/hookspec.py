
from borgcube.vendor import pluggy

hookspec = pluggy.HookspecMarker('borgcube')


@hookspec
def borgcube_web_urlpatterns(urlpatterns, js_info_dict):
    """
    Called once at setup time with the root *urlpatterns*.

    *js_info_dict* is the dict passed as keyword arguments to django.views.i18n.javascript_catalog,
    used for JavaScript internationalization (making message catalogs available).
    """


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


@hookspec(firstresult=True)
def borgcube_web_resolve(publisher, segment):
    """

    """


@hookspec
def borgcube_web_children(publisher, children):
    """

    """


@hookspec
def borgcube_web_jinja_env(env):
    """

    """
