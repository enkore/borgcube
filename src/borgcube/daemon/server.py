import errno
import logging
import signal
import sys
import time
import os

import zmq

from django.core.exceptions import ObjectDoesNotExist

from ..core.models import BackupJob, Job, JobConfig
from ..utils import set_process_name, hook

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
        self.socket = (context or zmq.Context.instance()).socket(zmq.REP)
        self.socket.bind(address)
        log.info('bound to %s', address)

        self.exit = False
        self.shutdown = False
        signal.signal(signal.SIGTERM, self.signal_terminate)
        signal.signal(signal.SIGINT, self.signal_shutdown)

    def signal_terminate(self, signum, stack_frame):
        log.info('Received signal %d, initiating exorcism', signum)
        self.exit = True
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    def signal_shutdown(self, signum, stack_frame):
        log.info('Received signal %d, initiating slow exorcism', signum)
        self.shutdown = True
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    def main_loop(self):
        while not self.exit:
            last_idle = time.perf_counter()
            while time.perf_counter() < last_idle + 1:
                if self.socket.poll(timeout=500):
                    request = self.socket.recv_json()
                    reply = self._handle_request(request)
                    self.socket.send_json(reply)
            self.idle()
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
        return {
            'success': False,
            'message': message % parameters
        }

    def fork(self):
        pid = os.fork()
        if pid:
            log.debug('Forked worker PID is %d', pid)
        else:
            self.socket.close()
            self.socket = None
            exit_by_exception()
        return pid


class APIServer(BaseServer):
    def __init__(self, address, context=None):
        super().__init__(address, context)
        os.setpgrp()
        # PID -> (command, params...)
        self.children = {}
        self.queue = []
        set_process_name('borgcubed [main process]')
        # TODO move to backupjob
        for job in BackupJob.objects.exclude(db_state__in=[s.value for s in BackupJob.State.STABLE]):
            job.set_failure_cause('borgcubed-restart')
        for job in BackupJob.objects.filter(db_state=BackupJob.State.job_created.value):
            self.queue_job(job)

    def handle_request(self, request):
        command = request['command']
        if command in self.commands:
            return self.commands[command](self, request)
        return hook.borgcubed_handle_request(apiserver=self, request=request)

    def idle(self):
        self.check_schedule()
        self.check_children()
        self.check_queue()

    def close(self):
        super().close()
        log.debug('Killing children')
        os.killpg(0, signal.SIGTERM)
        log.debug('Waiting for all children to die')
        while self.children:
            self.check_children()

    def queue_job(self, job):
        """
        Enqueue *job* instance for execution.
        """
        job_id = str(job.id)
        executor_class = hook.borgcubed_job_executor(job_id=job_id)
        if not executor_class:
            log.error('Cannot queue job %s: No JobExecutor found', job_id)
            return
        self.queue.append((executor_class, job_id))
        log.debug('Enqueued job %s', job.id)

    def cmd_cancel_job(self, request):
        try:
            job_id = request['job_id']
            job = Job.objects.get(id=job_id)
        except KeyError as ke:
            return self.error('Missing parameter %r', ke.args[0])
        except ObjectDoesNotExist:
            return self.error('No such JobConfig')
        log.info('Cancelling job %s', job_id)
        for i, (ec, item_job_id) in enumerate(self.queue[:]):
            if item_job_id == job_id:
                del self.queue[i]
                log.info('Cancelled queued job %s', job_id)
                return {'success': True}
        for pid, (command, item_job_id) in self.children.items():
            if item_job_id == job_id:
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

    commands = {
        'cancel-job': cmd_cancel_job,
        'log': cmd_log,
    }

    def check_schedule(self):
        """Check schedule. Are we supposed to do something right about now?"""

    def check_children(self):
        while self.children:
            try:
                pid, waitres = os.waitpid(-1, os.WNOHANG)
            except OSError as oe:
                if oe.errno == errno.ECHILD:
                    # Uh-oh
                    log.error('waitpid(2) failed with ECHILD, but we thought we had children')
                    for pid, (command, args) in self.children.items():
                        log.error('I am missing child %d, command %s %r', pid, command, args)
            if not pid:
                break
            signo = waitres & 0xFF
            code = (waitres & 0xFF00) >> 8
            failure = signo or code
            logger = log.error if failure else log.debug
            if signo:
                logger('Child %d exited with code %d on signal %d', pid, code, signo)
            else:
                logger('Child %d exited with code %d', pid, code)
            command, *params = self.children.pop(pid)
            logger('Command was: %s %r', command, params)
            if failure and command == 'run_job':
                job = BackupJob.objects.get(id=params[0])
                job.force_state(BackupJob.State.failed)
        self.exit |= self.shutdown and not self.children

    def check_queue(self):
        if self.shutdown:
            self.queue.clear()
            return
        nope = []
        while self.queue:
            executor_class, job_id = self.queue.pop()
            if not executor_class.can_run(job_id):
                nope.append((executor_class, job_id))
                continue
            executor_class.prefork(job_id)
            pid = self.fork()
            if pid:
                # Parent, gotta watch the kids
                self.children[pid] = executor_class.name, job_id
            else:
                set_process_name('borgcubed [%s %s]' % (executor_class.name, job_id))
                executor_class.run(job_id)
                sys.exit(0)
        self.queue.extend(nope)
