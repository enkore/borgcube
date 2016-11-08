
import os

import django
from django.conf import settings

from borg import logger

logger.configured = True

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'borgcube.web.settings')
django.setup()


def daemon():
    from borgcube.daemon.server import APIServer
    server = APIServer(settings.DAEMON_ADDRESS)
    server.main_loop()


def proxy():
    from borgcube.proxy import ReverseRepositoryProxy
    from .utils import log_to_daemon
    log_to_daemon()
    proxy = ReverseRepositoryProxy()
    proxy.serve()
