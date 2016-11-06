
import os

import django
from django.conf import settings

from borg import logger

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'borgcube.web.settings')

django.setup()

logger.configured = True


def daemon():
    from borgcube.daemon.server import APIServer
    server = APIServer(settings.DAEMON_ADDRESS)
    server.main_loop()


def proxy():
    from borgcube.proxy import ReverseRepositoryProxy
    proxy = ReverseRepositoryProxy()
    proxy.serve()
