import logging
import logging.config
import re
from itertools import islice
from threading import Lock, local

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage

import zmq

import transaction
import zodburi
from ZODB import DB

from borg.repository import Repository
from borg.remote import RemoteRepository
from borg.constants import UMASK_DEFAULT

import borgcube
from .vendor import pluggy

log = logging.getLogger(__name__)


_db = None
_db_local = local()
_db_lock = Lock()


def reset_db_connection():
    global _db
    with _db_lock:
        _db = None
        _db_local.__dict__.clear()


def db():
    global _db
    if not _db:
        with _db_lock:
            storage_factory, dbkw = zodburi.resolve_uri(settings.DB_URI)
            storage = storage_factory()
            _db = DB(storage, **dbkw)
        return db()
    try:
        return _db_local.conn
    except AttributeError:
        log.debug('Opening new database connection')
        _db_local.conn = _db.open()
        return _db_local.conn


def data_root():  # type: borgcube.core.models.DataRoot
    """
    Return a `DataRoot` instance.
    """
    try:
        root = _db_local.db.root
    except AttributeError:
        _db_local.db = db()
        root = _db_local.db.root
    try:
        return root.data_root
    except AttributeError:
        with transaction.manager as txn:
            txn.note('Initialized new data root.')
            log.info('Initializing new data root.')
            from borgcube.core.models import DataRoot
            root.data_root = DataRoot()
            return root.data_root


def paginate(request, things, num_per_page=40, prefix='', length=None):
    if prefix:
        prefix += '_'
    page = request.GET.get(prefix + 'page')
    paginator = IteratorPaginator(things, num_per_page, length=length)
    try:
        return paginator.page(page)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


class IteratorPaginator(Paginator):
    """
    Modified Django `Paginator` that works with iterables of known lengths, instead
    of requiring a len()-able, slice-able iterable.

    If *length* is left unspecified it behaves exactly like the standard Paginator.
    """

    def __init__(self, iterable, per_page, orphans=0,
                 allow_empty_first_page=True, length=None):
        super().__init__(None, per_page, orphans, allow_empty_first_page)
        if length is None:
            self.object_list = iterable
        else:
            self.count = length
            self.object_list = self.IteratorSlicer(iterable, length)

    class IteratorSlicer:
        def __init__(self, iterable, length):
            self.iterable = iterable
            self.length = length

        def __getitem__(self, item):
            if isinstance(item, slice):
                return list(islice(self.iterable, *item.indices(self.length)))
            raise ValueError()


def oid_bytes(oid):
    """Convert hex object id to bytes."""
    return bytes.fromhex(oid).rjust(8, b'\0')


_sentinel = object()


def find_oid(iterable, oid, default=_sentinel):
    for object in iterable:
        if object.oid == oid:
            return object
    else:
        if default is _sentinel:
            raise KeyError
        else:
            return default


def validate_regex(regex):
    try:
        re.compile(regex, re.IGNORECASE)
    except re.error as error:
        raise ValidationError(error.msg)


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
        from .daemon.utils import get_socket_addr
        logging_config = settings.LOGGING
        logging_config.update({
            'handlers': {
                'console': {
                    'level': 'DEBUG',
                    'class': 'borgcube.utils.DaemonLogHandler',
                    'formatter': 'standard',
                    'addr_or_socket': 'ipc://' + get_socket_addr('daemon'),
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

    __call__ = __enter__


def tee_job_logs(job):
    logfile = str(job.log_path())
    handler = logging.FileHandler(logfile)
    logging.root.addHandler(handler)


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
    import borgcube.web.hookspec
    import borgcube.daemon.hookspec

    pm = pluggy.PluginManager(project_name='borgcube', implprefix='borgcube')
    pm.add_hookspecs(borgcube.core.hookspec)
    pm.add_hookspecs(borgcube.web.hookspec)
    pm.add_hookspecs(borgcube.daemon.hookspec)
    pm.load_setuptools_entrypoints('borgcube0')
    hook = pm.hook

    log.debug('Loaded plugins: %s', ', '.join(name for name, plugin in pm.list_name_plugin()))
