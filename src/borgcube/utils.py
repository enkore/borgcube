import logging
import logging.config

from django.conf import settings

import zmq

from borg.repository import Repository
from borg.remote import RemoteRepository
from borg.constants import UMASK_DEFAULT

from .vendor import pluggy

log = logging.getLogger(__name__)


def open_repository(repository):
    if repository.location.proto == 'ssh':
        # TODO construct & pass args for stuff like umask and remote-path
        class Args:
            remote_ratelimit = None
            remote_path = repository.remote_borg
            umask = UMASK_DEFAULT

        return RemoteRepository(repository.location, exclusive=True, lock_wait=1, args=Args)
    else:
        return Repository(repository.location.path, exclusive=True, lock_wait=1)


try:
    from setproctitle import setproctitle as set_process_name
except ImportError:
    def set_process_name(name):
        pass


class DaemonLogHandler(logging.Handler):
    socket = None

    def __init__(self, addr_or_socket, level=logging.NOTSET, context=None):
        super().__init__(level)
        if isinstance(addr_or_socket, str):
            self.socket = (context or zmq.Context.instance()).socket(zmq.REQ)
            self.socket.connect(addr_or_socket)
        else:
            self.socket = addr_or_socket
        self.socket.linger = 2000
        self.socket.rcvtimeo = 2000
        self.socket.sndtimeo = 2000

    def emit(self, record):
        (self.formatter or logging._defaultFormatter).usesTime = lambda: True
        message = self.format(record)
        request = {
            'command': 'log',
            'name': record.name,
            'level': record.levelno,

            'path': record.pathname,
            'lineno': record.lineno,
            'function': record.funcName,

            'message': message,

            'created': record.created,
            'asctime': record.asctime,
            'pid': record.process,
        }
        self.socket.send_json(request)
        reply = self.socket.recv_json()
        if not reply['success']:
            raise RuntimeError('Error sending log message to borgcubed: %s' % reply['message'])


class log_to_daemon:
    def __enter__(self):
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

    def __exit__(self, exc_type, exc_val, exc_tb):
        handler = logging.getLogger('').handlers[-1]
        handler.socket.close()


def tee_job_logs(job):
    logfile = str(job.log_path())
    loggers = logging.Logger.manager.loggerDict
    handler = logging.FileHandler(logfile)
    for name, logger in loggers.items():
        if isinstance(logger, logging.PlaceHolder):
            logger = logging.getLogger(name)
        logger.addHandler(handler)


class LazyHook:
    def __getattr__(self, item):
        global hook
        if hook is self:
            raise AttributeError('Cannot call hook %r, configure_plugins() not called' % item)
        return getattr(hook, item)

pm = None
hook = LazyHook()


def configure_plugins():
    global pm
    global hook
    import borgcube.core.hookspec
    import borgcube.web.core.hookspec
    import borgcube.daemon.hookspec

    pm = pluggy.PluginManager(project_name='borgcube', implprefix='borgcube')
    pm.add_hookspecs(borgcube.core.hookspec)
    pm.add_hookspecs(borgcube.web.core.hookspec)
    pm.add_hookspecs(borgcube.daemon.hookspec)
    pm.load_setuptools_entrypoints('borgcube0')
    hook = pm.hook

    log.debug('Loaded plugins: %s', ', '.join(name for name, plugin in pm.list_name_plugin()))
