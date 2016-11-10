
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

from .utils import configure_plugins
configure_plugins()


def daemon():
    from .daemon.server import APIServer
    from .utils import hook
    hook.borgcube_startup(db=True, process='borgcubed')
    server = APIServer(settings.DAEMON_ADDRESS)
    server.main_loop()


def proxy():
    from .proxy import ReverseRepositoryProxy
    from .utils import log_to_daemon, hook
    hook.borgcube_startup(db=True, process='proxy')
    with log_to_daemon():
        proxy = ReverseRepositoryProxy()
        proxy.serve()


def manage():
    from django.core.management import execute_from_command_line
    from .utils import hook
    try:
        db = sys.argv[1] not in ('makemigrations', 'migrate')
    except IndexError:
        db = True
    hook.borgcube_startup(db=db, process='manage')
    sys.exit(execute_from_command_line())
