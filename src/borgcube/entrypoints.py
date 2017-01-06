
"""
This module contains the various entry points accessed by binaries installed into the system.

It also does the initialization of the various subsystems (Django, Logging, Plugins, ...).
"""

import os
import logging
import sys

import django
from django.conf import settings

from borg import logger

log = logging.getLogger(__name__)

logger.configured = True

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'borgcube.conf')
django.setup()

os.environ.setdefault('BORG_HOSTNAME_IS_UNIQUE', 'yes')

from .utils import configure_plugins
configure_plugins()


def _set_db_uri():
    from django.conf import settings
    if not settings.BUILTIN_ZEO:
        return
    from .daemon.client import APIClient
    client = APIClient()
    settings.DB_URI = client.zodburi()
    log.debug('Received DB_URI=%r from daemon', settings.DB_URI)


def daemon():
    from .daemon.server import APIServer
    from .utils import hook
    hook.borgcube_startup(db=True, process='borgcubed')
    server = APIServer(settings.DAEMON_ADDRESS)
    server.main_loop()


def proxy():
    from .proxy import ReverseRepositoryProxy
    from .utils import log_to_daemon, hook
    _set_db_uri()
    hook.borgcube_startup(db=True, process='proxy')
    #with log_to_daemon():
    proxy = ReverseRepositoryProxy()
    proxy.serve()


def manage():
    from django.core.management import execute_from_command_line
    from .utils import hook
    try:
        db = sys.argv[1] not in ('makemigrations', 'migrate')
    except IndexError:
        db = True
    _set_db_uri()
    logging.getLogger('borg.output.progress').setLevel('INFO')
    logging.getLogger('borg.output.stats').setLevel('INFO')
    hook.borgcube_startup(db=db, process='manage')
    sys.exit(execute_from_command_line())
