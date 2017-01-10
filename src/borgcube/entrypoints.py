
"""
This module contains the various entry points accessed by binaries installed into the system.

It also does the initialization of the various subsystems (Django, Logging, Plugins, ...).
"""

import os
import logging
import sys
from urllib.parse import urlunsplit

import django
from django.conf import settings

from borg import logger

log = logging.getLogger(__name__)

logger.configured = True

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'borgcube.conf')
django.setup()

os.environ['BORG_HOSTNAME_IS_UNIQUE'] = 'yes'

from .utils import configure_plugins
configure_plugins()


def _set_db_uri():
    if not settings.BUILTIN_ZEO:
        return
    from .daemon.utils import get_socket_addr
    settings.DB_URI = urlunsplit(('zeo', '', get_socket_addr('zeo'), 'wait_timeout=5', ''))
    log.debug('Real DB_URI (at daemon) is %r', settings.DB_URI)


def daemon():
    from .daemon.server import APIServer
    from .daemon.utils import get_socket_addr
    from .utils import hook
    hook.borgcube_startup(process='borgcubed')
    server = APIServer('ipc://' + get_socket_addr('daemon'))
    server.main_loop()


def proxy():
    from .proxy import ReverseRepositoryProxy
    from .utils import log_to_daemon, hook
    with log_to_daemon():
        _set_db_uri()
        hook.borgcube_startup(process='proxy')
        proxy = ReverseRepositoryProxy()
        proxy.serve()


def manage():
    from django.core.management import execute_from_command_line
    from .utils import hook
    _set_db_uri()
    logging.getLogger('borg.output.progress').setLevel('INFO')
    logging.getLogger('borg.output.stats').setLevel('INFO')
    hook.borgcube_startup(process='manage')
    sys.exit(execute_from_command_line())
