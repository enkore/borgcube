import errno
import logging
import signal
import sys
import time
import os
from pathlib import Path
from subprocess import check_output, check_call, CalledProcessError

import zmq

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from borg.helpers import bin_to_hex

from ..core.models import Job, JobConfig
from ..utils import set_process_name


log = logging.getLogger('borgcubed')


def check_schedules():
    pass


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
                    reply = self.handle_request(request)
                    self.socket.send_json(reply)
            self.idle()
        self.close()
        log.info('Exorcism successful. Have a nice day.')

    def handle_request(self, request):
        """Handle *request*, return reply."""
        if not isinstance(request, dict):
            return self.error('invalid request: a dictionary is required.')
        command = request.get('command')
        if command not in self.commands:
            log.error('invalid request was %r', request)
            return self.error('invalid request: no or invalid command.')
        try:
            return self.commands[command](self, request)
        except Exception as exc:
            log.exception('Error during request processing. Request was %r', request)
            if not isinstance(exc, zmq.ZMQError) and self.socket:
                # Probably need to send a reply
                return self.error('Uncaught exception during processing')
            sys.exit(1)

    def idle(self):
        pass

    def close(self):
        self.socket.close()

    def error(self, message, *parameters):
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
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        return pid

    commands = {}


class APIServer(BaseServer):
    def __init__(self, address, context=None):
        super().__init__(address, context)
        os.setpgrp()
        # PID -> (command, params...)
        self.children = {}
        self.queue = []
        set_process_name('borgcubed [main process]')
        for job in Job.objects.exclude(db_state__in=[s.value for s in Job.State.STABLE]):
            job.set_failure_cause('borgcubed-restart')
        for job in Job.objects.filter(db_state=Job.State.job_created.value):
            self.queue_job(job)

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

    def cmd_initiate_job(self, request):
        # TODO catch all!111 the exceptions, log'em.
        # TODO per-job log file somewhere. $BASE_LOG/$HOSTNAME/$TIMESTAMP-$JOB_ID
        try:
            client_hostname = request['client']
            jobconfig_id = request['job_config']
        except KeyError as ke:
            return self.error('Missing parameter %r', ke.args[0])
        try:
            job_config = JobConfig.objects.get(client=client_hostname, id=jobconfig_id)
        except ObjectDoesNotExist:
            return self.error('No such JobConfig')
        job = Job.objects.create(
            repository=job_config.repository,
            config=job_config,
            client=job_config.client
        )
        log.info('Created job %s for client %s, job config %d', job.id, job_config.client.hostname, job_config.id)
        self.queue_job(job)
        return {
            'success': True,
            'job': str(job.id),
        }

    def queue_job(self, job):
        log.debug('Enqueued job %s', job.id)
        self.queue.append((self.can_run_job, self.prefork_job, self.run_job, str(job.id)))

    def can_run_job(self, job_id):
        job = Job.objects.get(id=job_id)
        blocking_jobs = Job.objects.filter(repository=job.repository).exclude(db_state__in=[s.value for s in Job.State.STABLE])
        job_is_blocked = blocking_jobs.exists()
        if job_is_blocked:
            log.debug('Job %s blocked by running jobs: %s', job_id, ' '.join('{} ({})'.format(job.id, job.db_state) for job in blocking_jobs))
        return not job_is_blocked

    def prefork_job(self, job_id):
        job = Job.objects.get(id=job_id)
        job.update_state(Job.State.job_created, Job.State.client_preparing)

    def run_job(self, job_id):
        job = Job.objects.get(id=job_id)
        set_process_name('borgcubed [run-job %s]' % job_id)
        executor = JobExecutor(job)
        executor.execute()

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
        'initiate-job': cmd_initiate_job,
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
            if failure and command == 'run-job':
                job = Job.objects.get(id=params[0])
                if job.force_state(Job.State.failed):
                    logger('Job was not marked as failed; rectified that')
        self.exit |= self.shutdown and not self.children

    def check_queue(self):
        if self.shutdown:
            self.queue.clear()
            return
        nope = []
        while self.queue:
            predicate, prefork, method, *args = self.queue.pop()
            if not predicate(*args):
                nope.append((predicate, prefork, method, *args))
                continue
            prefork(*args)
            pid = self.fork()
            if pid:
                # Parent, gotta watch the kids
                self.children[pid] = method.__name__, *args
            else:
                method(*args)
                sys.exit(0)
        self.queue.extend(nope)


import configparser
import shlex
import shutil

from borg.helpers import get_cache_dir, Manifest, Location
from borg.cache import Cache
from borg.key import PlaintextKey
from borg.repository import Repository
from borg.locking import LockTimeout, LockFailed, LockError, LockErrorT

from borgcube.keymgt import synthesize_client_key, SyntheticManifest
from borgcube.utils import open_repository, tee_job_logs


def cpe_means_connection_failure(called_process_error):
    command = called_process_error.cmd[0]
    exit_code = called_process_error.returncode
    rsync_errors = (2, 3, 5, 6, 10, 11, 12, 13, 14, 21, 22, 23, 24, 25, 30, 35)
    # SSH connection error, or rsync error, which is likely also connection related
    return (('ssh' in command and exit_code == 255) or
            ('rsync' in command and exit_code in rsync_errors))


class JobExecutor:
    def __init__(self, job):
        tee_job_logs(job)
        self.job = job
        self.client = job.client
        self.repository = job.repository
        self.remote_cache_dir = self.find_remote_cache_dir()

    def execute(self):
        try:
            self.synthesize_crypto()
            self.transfer_cache()
            self.job.update_state(Job.State.client_preparing, Job.State.client_prepared)

            self.remote_create()
            self.client_cleanup()
            self.job.update_state(Job.State.client_cleanup, Job.State.done)
            log.info('Job %s completed successfully', self.job.id)
        except CalledProcessError as cpe:
            self.job.force_state(Job.State.failed)
            if not self.analyse_job_process_error(cpe):
                raise
            self.job.save()
        except Repository.DoesNotExist:
            self.job.set_failure_cause('repository-does-not-exist')
            log.error('Job %s failed because the repository %r does not exist', self.job.id, self.repository.url)
        except Repository.CheckNeeded:
            # TODO: schedule check automatically?
            self.job.set_failure_cause('repository-check-needed')
            log.error('Job %s failed because the repository %r needs a check run', self.job.id, self.repository.url)
        except Repository.InsufficientFreeSpaceError:
            self.job.set_failure_cause('repository-enospc')
            log.error('Job %s failed because the repository %r had not enough free space', self.job.id, self.repository.url)
        except LockTimeout as lock_error:
            if get_cache_dir() in lock_error.args[0]:
                self.job.set_failure_cause('cache-lock-timeout')
                log.error('Job %s failed because locking the cache timed out', self.job)
            else:
                self.job.set_failure_cause('repository-lock-timeout')
                log.error('Job %s failed because locking the repository %r timed out', self.job, self.repository.url)
        except LockFailed as lock_error:
            error = lock_error.args[1]
            if get_cache_dir() in lock_error.args[0]:
                self.job.set_failure_cause('cache-lock-failed', error=error)
                log.error('Job %s failed because locking the cache failed (%s)', self.job, error)
            else:
                self.job.set_failure_cause('repository-lock-failed', error=error)
                log.error('Job %s failed because locking the repository %r failed (%s)', self.job, self.repository.url, error)
        except (LockError, LockErrorT) as lock_error:
            error = lock_error.get_message()
            self.job.set_failure_cause('lock-error', error=error)
            log.error('Job %s failed because a locking error occured: %s', self.job, error)

    def analyse_job_process_error(self, called_process_error):
        if cpe_means_connection_failure(called_process_error):
            self.job.set_failure_cause('client-connection-failed', command=called_process_error.cmd, exit_code=called_process_error.returncode)
            log.error('Job %s failed due to client connection failure', self.job.id)
            return True
        return False

    def synthesize_crypto(self):
        with open_repository(self.repository) as repository:
            manifest, key = Manifest.load(repository)
            client_key = synthesize_client_key(key, repository)
            if not isinstance(client_key, PlaintextKey):
                self.job.data['client_key_data'] = client_key.get_key_data()

            client_manifest = SyntheticManifest(client_key)
            self.job.data['client_manifest_data'] = bin_to_hex(client_manifest.write())
            self.job.data['client_manifest_id_str'] = client_manifest.id_str
            self.job.save()

    def transfer_cache(self):
        cache_path = Path(get_cache_dir()) / self.repository.id
        log.debug('transfer_cache: local cache is %r', cache_path)
        job_cache_path = self.create_job_cache(cache_path)

        # TODO per-client files cache, on the client or on the server?
        # TODO rsh, rsh_options

        connstr = self.client.connection.remote + ':' + self.remote_cache_dir + self.repository.id + '/'
        rsync = ('rsync', '-rI', '--delete')
        log.debug('transfer_cache: rsync connection string is %r', connstr)
        log.debug('transfer_cache: auxiliary files')
        try:
            check_output(('ssh', self.client.connection.remote, 'mkdir', '-p', self.remote_cache_dir + self.repository.id + '/'))
            check_call(rsync + (str(job_cache_path) + '/', connstr))
        finally:
            shutil.rmtree(str(job_cache_path))
        log.debug('transfer_cache: chunks cache')
        chunks_cache = cache_path / 'chunks'
        check_call(rsync + (str(chunks_cache), connstr))
        log.debug('transfer_cache: done')

    def create_job_cache(self, cache_path):
        self.ensure_cache(cache_path)
        job_cache_path = cache_path / str(self.job.id)
        job_cache_path.mkdir()
        log.debug('create_job_cache: path is %r', job_cache_path)

        (job_cache_path / 'chunks.archive.d').touch()
        (job_cache_path / 'files').touch()
        with (job_cache_path / 'README').open('w') as fd:
            fd.write('This is a Borg cache')
        config = configparser.ConfigParser(interpolation=None)
        config.add_section('cache')
        config.set('cache', 'version', '1')
        config.set('cache', 'repository', self.repository.id)
        config.set('cache', 'manifest',  self.job.data['client_manifest_id_str'])
        # TODO: path canoniciialailaition thing
        config.set('cache', 'previous_location', Location(self.job_location).canonical_path().replace('/./', '/~/'))
        with (job_cache_path / 'config').open('w') as fd:
            config.write(fd)

        return job_cache_path

    @property
    def job_location(self):
        return settings.SERVER_LOGIN + ':' + str(self.job.id)

    def remote_create(self):
        connection = self.client.connection

        command_line = [connection.rsh]
        if connection.ssh_identity_file:
            command_line += '-i', connection.ssh_identity_file
        if connection.rsh_options:
            command_line.append(connection.rsh_options)
        command_line.append(connection.remote)
        command_line.append('BORG_CACHE_DIR=' + self.remote_cache_dir)
        command_line.append(connection.remote_borg)
        command_line.append('create')
        command_line.append(self.job_location + '::' + self.job.archive_name)

        if settings.SERVER_PROXY_PATH:
            command_line += '--remote-path', settings.SERVER_PROXY_PATH

        config = self.job.config.config
        assert config['version'] == 1, 'Unknown JobConfig version: %r' % config['version']
        for path in config['paths']:
            command_line.append(shlex.quote(path))
        for exclude in config['excludes']:
            command_line += '--exclude', shlex.quote(exclude)
        if config['one_file_system']:
            command_line += '--one-file-system',
        if config['read_special']:
            command_line += '--read-special',
        if config['ignore_inode']:
            command_line += '--ignore-inode',
        command_line += '--checkpoint-interval', str(config['checkpoint_interval'])
        command_line += '--compression', config['compression']
        extra_options = config.get('extra_options')
        if extra_options:
            command_line += extra_options,

        log.debug('Built command line: %r', command_line)
        try:
            check_call(command_line)
        except CalledProcessError as cpe:
            if cpe.returncode == 1:
                self.job.refresh_from_db()
                self.job.data['borg_warning'] = True
                self.job.save()
            else:
                raise
        else:
            self.job.refresh_from_db()
        log.debug('remote create finished (success/warning)')
        self.job.repository.refresh_from_db()
        self.job.update_state(Job.State.client_in_progress, Job.State.client_done)

    def client_cleanup(self):
        self.job.update_state(Job.State.client_done, Job.State.client_cleanup)
        # TODO delete checkpoints

        # TODO do we actually want this? if we leave the cache, the next job has a good chance of rsyncing just a delta
        # TODO perhaps a per-client setting, to limit space usage on the client with multiple repositories.

    def check_archive_chunks_cache(self):
        archives = Path(get_cache_dir()) / self.repository.id / 'chunks.archive.d'
        if archives.is_dir():
            log.info('Disabling archive chunks cache of %s', archives.parent)
            shutil.rmtree(str(archives))
            archives.touch()

    def ensure_cache(self, cache_path):
        if not cache_path.is_dir():
            log.info('No cache found, creating one')
        with open_repository(self.repository) as repository:
            manifest, key = Manifest.load(repository)
            with Cache(repository, key, manifest, path=str(cache_path), lock_wait=1) as cache:
                cache.commit()
            self.check_archive_chunks_cache()

    def find_remote_cache_dir(self):
        remote_cache_dir = (self.client.connection.remote_cache_dir or '.cache/borg/')
        escape = not self.client.connection.remote_cache_dir
        if remote_cache_dir[-1] != '/':
            remote_cache_dir += '/'
        if escape:
            remote_cache_dir = shlex.quote(remote_cache_dir)
        log.debug('remote_cache_dir is %r', remote_cache_dir)
        return remote_cache_dir
