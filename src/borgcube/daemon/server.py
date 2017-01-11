import errno
import logging
import signal
import stat
import sys
import time
import os
from urllib.parse import urlunsplit, urlsplit
from collections import defaultdict

import zmq

import zodburi
import transaction

from django.conf import settings

import borgcube
from ..core.models import Job
from ..utils import set_process_name, hook, data_root, reset_db_connection, log_to_daemon
from .utils import get_socket_addr

log = logging.getLogger('borgcubed')


def exit_by_exception():
    class SignalException(BaseException):
        pass

    def signal_fork(signum, stack_frame):
        log.info('Received signal %d, procuring hariki', signum)
        raise SignalException(signum)

    def excepthook(exc_type, exc_value, exc_trace):
        if exc_type is SignalException:
            sys.exit(1)
        else:
            sys.__excepthook__(exc_type, exc_value, exc_trace)

    sys.excepthook = excepthook
    signal.signal(signal.SIGINT, signal_fork)
    signal.signal(signal.SIGTERM, signal_fork)


class BaseServer:
    def __init__(self, address, context=None):
        log.info('borgcubed %s starting', borgcube.__version__)
        self.socket = (context or zmq.Context.instance()).socket(zmq.REP)
        self.socket.bind(address)
        log.debug('bound to %s', address)

        self.shutdown = False
        signal.signal(signal.SIGTERM, self.signal_terminate)
        signal.signal(signal.SIGINT, self.signal_terminate)

        self.stats = defaultdict(int)
        self.up = time.monotonic()

    @property
    def uptime(self):
        return time.monotonic() - self.up

    def signal_terminate(self, signum, stack_frame):
        log.info('Received signal %d, initiating exorcism', signum)
        self.shutdown = True
        signal.signal(signum, signal.SIG_IGN)

    def main_loop(self):
        log.info('Daemon reporting for duty.')
        while not self.shutdown:
            self.idle()
            last_idle = time.perf_counter()
            while time.perf_counter() < last_idle + 1:
                if self.socket.poll(timeout=500):
                    request = self.socket.recv_json()
                    reply = self._handle_request(request)
                    self.socket.send_json(reply)
        self.close()
        log.info('Exorcism successful. Have a nice day.')

    def _handle_request(self, request):
        """Handle *request*, return reply."""
        if not isinstance(request, dict):
            return self.error('invalid request: a dictionary is required.')
        command = request.get('command')
        if not command:
            log.error('invalid request was %r', request)
            return self.error('invalid request: no command.')
        try:
            reply = self.handle_request(request)
            if reply is None:
                log.error('invalid request was %r', request)
                return self.error('invalid request: not handled')
            return reply
        except Exception as exc:
            log.exception('Error during request processing. Request was %r', request)
            if not isinstance(exc, zmq.ZMQError) and self.socket:
                # Probably need to send a reply
                return self.error('Uncaught exception during processing')
            sys.exit(1)

    def handle_request(self, request):
        pass

    def idle(self):
        pass

    def close(self):
        self.socket.close()
        self.socket = None
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    def error(self, message, *parameters):
        """
        Log error *message* formatted (%) with *parameters*. Return response dictionary.
        """
        log.error('Request failed: ' + message, *parameters)
        self.stats['failed_requests'] += 1
        return {
            'success': False,
            'message': message % parameters
        }

    def fork(self):
        pid = os.fork()
        if pid:
            log.debug('Forked worker PID is %d', pid)
            self.stats['forks'] += 1
        else:
            os.setpgrp()
            self.socket.close()
            self.socket = None
            exit_by_exception()
        return pid


class Service:
    def __init__(self, fork):
        self.fork = fork

    def __str__(self):
        return self.__class__.__name__

    def launch(self):
        raise NotImplementedError


class ZEOService(Service):
    def launch(self):
        self.check()

        received = False

        def set_received(*_):
            nonlocal received
            received = True

        signal.signal(signal.SIGUSR1, set_received)
        pid = self.fork_zeo()
        if not received:
            while not signal.sigtimedwait([signal.SIGUSR1], 1):
                pid, waitres = os.waitpid(pid, os.WNOHANG)
                if pid:
                    log.error('Database server failed to start (check log above).')
                    sys.exit(1)

        settings.DB_URI = urlunsplit(('zeo', '', self.zeo_path, '', ''))
        log.debug('Launched built-in ZEO')
        return pid

    def check(self):
        """Verify correct permissions and ownership of database files."""
        scheme, _, file, _, _ = urlsplit(settings.DB_URI)
        if scheme != 'file':
            log.warning('DB_URI does not point to a file but %s -- forgot to set "BUILTIN_ZEO = False"?', scheme)
            return

        try:
            st = os.stat(file)
        except FileNotFoundError:
            # Database not created yet, not an error.
            return

        error = False
        if st.st_uid != os.geteuid():
            log.error('Database file %s has wrong owner: %d (file) vs %d (daemon user)', file, st.st_uid, os.geteuid())
            error = True
        if st.st_gid != os.getegid():
            log.error('Database file %s has wrong group: %d (file) vs %d (daemon user)', file, st.st_gid, os.getegid())
            # not a critical error, could be, theoretically, on purpose
        if error:
            sys.exit(1)

        # Fix perms, if any
        perms = stat.S_IMODE(st.st_mode)
        perms_should_be = perms & ~stat.S_IRWXO
        if perms != perms_should_be:
            try:
                os.chmod(file, perms_should_be)
            except OSError as ose:
                log.debug('Tried to fix permissions on database file, but it didn\'t work: %s', file, ose)

    def fork_zeo(self):
        self.zeo_path = get_socket_addr('zeo')
        try:
            os.unlink(self.zeo_path)
        except OSError:
            pass
        pid = self.fork()
        if pid:
            return pid
        else:
            from ZEO.StorageServer import StorageServer
            set_process_name('borgcubed [database process]')

            storage_factory, _ = zodburi.resolve_uri(settings.DB_URI)
            storage = storage_factory()

            prev_umask = os.umask(0o177)
            server = StorageServer(
                addr=self.zeo_path,
                storages={'1': storage},
            )
            os.umask(prev_umask)

            os.kill(os.getppid(), signal.SIGUSR1)
            try:
                server.loop()
            finally:
                server.close()
                sys.exit(0)


class WebService(Service):
    def launch(self):
        pid = self.fork()
        if pid:
            return pid
        else:
            from wsgiref.simple_server import make_server
            from borgcube.web.wsgi import get_wsgi_application
            from .utils import ThreadPoolWSGIServer
            host, port = settings.BUILTIN_WEB.rsplit(':', maxsplit=1)

            set_process_name('borgcubed [web process]')

            log.info('Serving HTTP on http://%s:%s', host, port)

            if settings.DEBUG:
                log.warning('DEBUG mode is enabled. This is rather dangerous.')

                if host not in ('127.0.0.1', 'localhost'):
                    log.error('DEBUG mode is not possible for non-local host %s', host)
                    sys.exit(1)

            httpd = make_server(host, int(port), get_wsgi_application(), server_class=ThreadPoolWSGIServer)
            try:
                httpd.serve_forever()
            finally:
                httpd.join()
                sys.exit(0)


class APIServer(BaseServer):
    def __init__(self, address, context=None):
        super().__init__(address, context)
        # PID -> (command, params...)
        self.children = {}
        # PID -> service instance
        self.services = {}
        self.queue = []
        set_process_name('borgcubed [main process]')
        if settings.BUILTIN_ZEO:
            self.launch_service(ZEOService)
        if settings.BUILTIN_WEB:
            self.launch_service(WebService)

        hook.borgcubed_startup(apiserver=self)
        db = data_root()

        with transaction.manager as txn:
            txn.note('borgcubed starting')
            for state, jobs in db.jobs_by_state.items():
                if state in Job.State.STABLE:
                    continue
                for job in jobs.values():
                    job.set_failure_cause('borgcubed-restart')
                    txn.note(' - Failing previously running job %s due to restart' % job.id)
            for job in db.jobs_by_state.get(Job.State.job_created, {}).values():
                self.queue_job(job)
                txn.note(' - Queuing job %s' % job.id)

    def launch_service(self, service):
        inst = service(self.fork)
        pid = inst.launch()
        self.services[pid] = inst

    def handle_request(self, request):
        command = request['command']
        self.stats['requests'] += 1
        if command in self.commands:
            return self.commands[command](self, request)
        return hook.borgcubed_handle_request(apiserver=self, request=request)

    def idle(self):
        transaction.begin()
        hook.borgcubed_idle(apiserver=self)
        self.check_children()
        self.queue_new_jobs()
        self.check_queue()

    def close(self):
        super().close()
        log.debug('Killing children')
        for pid in self.children:
            os.killpg(pid, signal.SIGTERM)
        log.debug('Waiting for all children to die')
        while self.children:
            self.check_children()
        log.debug('Killing services')
        for pid in self.services:
            os.killpg(pid, signal.SIGTERM)
        while self.services:
            self.check_children()

    def queue_job(self, job):
        """
        Enqueue *job* instance for execution.
        """
        executor_class = job.executor
        self.queue.append((executor_class, job))
        log.debug('Enqueued job %s', job.id)

    def queue_new_jobs(self):
        for job in data_root().jobs_by_state.get(Job.State.job_created, {}).values():
            self.queue_job(job)

    def cmd_cancel_job(self, request):
        try:
            job_id = int(request['job_id'])
        except (ValueError, KeyError) as ke:
            return self.error('Missing parameter %r', ke.args[0])
        try:
            job = data_root().jobs[job_id]
        except KeyError:
            return self.error('No such job')
        log.info('Cancelling job %s', job_id)
        if job.state not in job.State.STABLE:
            job.force_state(job.State.cancelled)
        # TODO update
        for i, (ec, item_job) in enumerate(self.queue[:]):
            if item_job == job:
                del self.queue[i]
                log.info('Cancelled queued job %s', job_id)
                return {'success': True}
        for pid, (command, item_job) in self.children.items():
            if item_job == job:
                os.kill(pid, signal.SIGTERM)
                log.info('Cancelled job %s (worker pid was %d)', job_id, pid)
                return {'success': True}
        return {'success': True, 'message': 'Job neither active nor queued'}

    def cmd_log(self, request):
        try:
            name = str(request['name'])
            level = int(request['level'])
            path = str(request['path'])
            lineno  = int(request['lineno'])
            message = str(request['message'])
            function = str(request['function'])
            created = float(request['created'])
            asctime = str(request['asctime'])
            pid = int(request['pid'])
        except KeyError as ke:
            return self.error('Missing parameter %r', ke.args[0])
        except (ValueError, TypeError) as exc:
            return self.error('Erroneous parameter: %s', exc)
        record = logging.LogRecord(**{
            'name': name,
            'pathname': path,
            'level': level,
            'lineno': lineno,
            'msg': '%s',
            'args': (message,),
            'exc_info': None,
        })
        record.__dict__.update({
            'function': function,
            'created': created,
            'asctime': asctime,
            'pid': pid,
        })
        logging.getLogger(name).handle(record)
        return {
            'success': True,
        }

    def cmd_stats(self, request):
        stats = dict(self.stats)
        stats['uptime'] = self.uptime
        return {
            'stats': stats,
            'success': True,
        }

    commands = {
        'cancel-job': cmd_cancel_job,
        'log': cmd_log,
        'stats': cmd_stats,
    }

    def check_children(self):
        while self.children or self.services:
            try:
                pid, waitres = os.waitpid(-1, os.WNOHANG)
            except OSError as oe:
                if oe.errno == errno.ECHILD:
                    # Uh-oh
                    log.error('waitpid(2) failed with ECHILD, but we thought we had children')
                    for pid, (command, job) in self.children.items():
                        log.error('I am missing child %d, command %s %s', pid, command, job.id)
                    self.children.clear()
                    break
            if not pid:
                break
            signo = waitres & 0xFF
            code = (waitres & 0xFF00) >> 8
            failure = signo or code
            if failure:
                self.stats['job_failures'] += 1
            else:
                self.stats['job_successes'] += 1
            logger = log.error if failure else log.debug
            if signo:
                logger('Child %d exited with code %d on signal %d', pid, code, signo)
            else:
                logger('Child %d exited with code %d', pid, code)
            service = self.services.pop(pid, None)
            if service:
                logger('Child was service process %s', service)
                continue
            command, job = self.children.pop(pid)
            logger('Command was: %s %r', command, job.id)
            if code or signo:
                if job.state not in job.State.STABLE or job.state == job.State.job_created:
                    job.force_state(job.State.failed)
            hook.borgcubed_job_exit(apiserver=self, job=job, exit_code=code, signo=signo)

    def check_queue(self):
        if self.shutdown:
            self.queue.clear()
            return
        nope = []
        while self.queue:
            executor_class, job = self.queue.pop()
            if not executor_class.can_run(job):
                nope.append((executor_class, job))
                continue
            try:
                executor_class.prefork(job)
            except Exception:
                log.exception('Unhandled exception in %s.prefork(%s)', executor_class.__name__, job.id)
                job.force_state(job.State.failed)
                continue

            id = job.id
            pid = self.fork()
            if pid:
                # Parent, gotta watch the kids
                self.children[pid] = executor_class.name, job
            else:
                # One important thing to note about ZODB is that live objects are connected to their DB instance
                # which is entangled with the async/client business. When forking we need to get rid of these FDs
                # (can't use them from two processes at once), which also means we can't re-use objects across
                # a fork.
                # (Technically *job* was live and loaded, so we could use it here, but to make this more explicit
                # we don't).
                log_to_daemon()
                set_process_name('borgcubed [%s %s]' % (executor_class.name, id))
                reset_db_connection()
                job = data_root().jobs[id]
                executor_class.run(job)
                sys.exit(0)
        self.queue.extend(nope)
