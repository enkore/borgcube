
import os
import logging.config
from pathlib import Path

import django
from django.conf import settings

from borg import logger

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'borgcube.web.settings')

django.setup()

logger.configured = True

logs_path = Path(settings.SERVER_LOGS_DIR)
logs_path.mkdir(parents=True, exist_ok=True)


def log_to_daemon():
    logging_config = settings.LOGGING
    logging_config.update({
        'handlers': {
            'console': {
                'level': 'DEBUG',
                'class': 'borgcube.utils.DaemonLogHandler',
                'formatter': 'standard',
                'addr_or_socket': settings.DAEMON_ADDRESS,
            },
        },
        'formatters': {
            'standard': {
                'format': '%(message)s'
            },
        },
    })
    logging.config.dictConfig(logging_config)


def daemon():
    from borgcube.daemon.server import APIServer
    server = APIServer(settings.DAEMON_ADDRESS)
    server.main_loop()


def proxy():
    from borgcube.proxy import ReverseRepositoryProxy
    log_to_daemon()
    proxy = ReverseRepositoryProxy()
    proxy.serve()
