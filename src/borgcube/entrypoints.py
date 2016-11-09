
import os
import logging
import sys

import django
from django.conf import settings

from borg import logger

log = logging.getLogger(__name__)

logger.configured = True

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'borgcube.web.settings')
django.setup()

os.environ.setdefault('BORG_HOSTNAME_IS_UNIQUE', 'yes')


def daemon():
    from borgcube.daemon.server import APIServer
    from .utils import configure_plugins
    configure_plugins()
    server = APIServer(settings.DAEMON_ADDRESS)
    server.main_loop()


def proxy():
    from borgcube.proxy import ReverseRepositoryProxy
    from .utils import log_to_daemon, configure_plugins
    with log_to_daemon():
        configure_plugins()
        proxy = ReverseRepositoryProxy()
        proxy.serve()


def manage():
    from django.core.management import execute_from_command_line
    from .utils import configure_plugins
    configure_plugins()
    sys.exit(execute_from_command_line())
