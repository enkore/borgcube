
from django.utils import translation

from jinja2 import Environment

from borgcube.utils import hook


def environment(**options):
    env = Environment(**options)
    env.install_gettext_translations(translation, newstyle=True)

    from .templatetags.borgcube import get_url, field_name, compression_name, summarize_archive, job_outcome, format_timedelta, json, describe_recurrence
    from django.utils.html import escapejs
    from django.template.defaultfilters import linebreaks, linebreaksbr, yesno

    env.filters.update({
        'get_url': get_url,  # TODO: remove
        'field_name': field_name,
        'compression_name': compression_name,
        'summarize_archive': summarize_archive,
        'job_outcome': job_outcome,
        'format_timedelta': format_timedelta,
        'json': json,
        'describe_recurrence': describe_recurrence,

        'escapejs': escapejs,
        'linebreaks': linebreaks,
        'linebreaksbr': linebreaksbr,
        'yesno': yesno,
    })

    hook.borgcube_web_jinja_env(env=env)
    return env
