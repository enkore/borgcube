
import os
import logging
import sys

import django
from django.conf import settings

from borg import logger

from .vendor import pluggy

log = logging.getLogger(__name__)

logger.configured = True

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'borgcube.web.settings')
django.setup()

os.environ.setdefault('BORG_HOSTNAME_IS_UNIQUE', 'yes')


def configure_plugins():
    global pm
    import borgcube.core.hookspec
    import borgcube.web.core.hookspec

    pm = pluggy.PluginManager('borgcube', 'borgcube')
    pm.add_hookspecs(borgcube.core.hookspec)
    pm.add_hookspecs(borgcube.web.core.hookspec)
    pm.load_setuptools_entrypoints('borgcube0')

    log.info('Loaded plugins: %s', ', '.join(name for name, plugin in pm.list_name_plugin()))
    pm.hook.borgcube_startup()


def daemon():
    from borgcube.daemon.server import APIServer
    configure_plugins()
    server = APIServer(settings.DAEMON_ADDRESS)
    server.main_loop()


def proxy():
    from borgcube.proxy import ReverseRepositoryProxy
    from .utils import log_to_daemon
    log_to_daemon()
    configure_plugins()
    proxy = ReverseRepositoryProxy()
    proxy.serve()


def manage():
    from django.core.management import execute_from_command_line
    configure_plugins()
    sys.exit(execute_from_command_line())
