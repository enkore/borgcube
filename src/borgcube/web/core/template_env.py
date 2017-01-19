
from django.utils import translation

from jinja2 import Environment

from borgcube.utils import hook


def environment(**options):
    env = Environment(**options)
    env.install_gettext_translations(translation, newstyle=True)
    hook.borgcube_web_jinja_env(env=env)
    return env
