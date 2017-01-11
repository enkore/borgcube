
"""
This module contains the various entry points accessed by binaries installed into the system.

It also does the initialization of the various subsystems (Django, Logging, Plugins, ...).
"""

import os
import logging
import sys
import traceback
from functools import wraps
from urllib.parse import urlunsplit

from zmq.error import Again

import django
from django.conf import settings

from borg import logger
from borg.helpers import Error

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


def errhandler(func):
    @wraps(func)
    def wrapper():
        exit_code = 1
        tb_log_level = logging.DEBUG

        try:
            return func()
        except Again:
            print('Couldn\'t connect to the borgcube daemon. Is it running?', file=sys.stderr)
            return 1
        except Error as e:
            msg = e.get_message()
            if e.traceback:
                tb_log_level = logging.ERROR
            tb = traceback.format_exc()
            exit_code = e.exit_code
        except KeyboardInterrupt:
            msg = 'Keyboard interrupt'
            tb = traceback.format_exc()

        if msg:
            log.error(msg)
        if tb:
            log.log(tb_log_level, tb)
        return exit_code
    return wrapper


@errhandler
def daemon():
    from .daemon.server import APIServer
    from .daemon.utils import get_socket_addr
    from .utils import hook
    hook.borgcube_startup(process='borgcubed')
    server = APIServer('ipc://' + get_socket_addr('daemon'))
    server.main_loop()


@errhandler
def proxy():
    from .proxy import ReverseRepositoryProxy
    from .utils import log_to_daemon, hook
    with log_to_daemon():
        _set_db_uri()
        hook.borgcube_startup(process='proxy')
        proxy = ReverseRepositoryProxy()
        proxy.serve()


@errhandler
def manage():
    from django.core.management import execute_from_command_line
    from .utils import hook
    _set_db_uri()
    logging.getLogger('borg.output.progress').setLevel('INFO')
    logging.getLogger('borg.output.stats').setLevel('INFO')
    hook.borgcube_startup(process='manage')
    sys.exit(execute_from_command_line())
