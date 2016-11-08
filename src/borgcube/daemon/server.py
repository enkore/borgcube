import errno
import logging
import signal
import sys
import os
from pathlib import Path

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
        signal.signal(signal.SIGTERM, self.signal_terminate)
        signal.signal(signal.SIGINT, self.signal_terminate)

    def signal_terminate(self, signum, stack_frame):
        log.info('Received signal %d, initiating exorcism', signum)
        self.exit = True

    def main_loop(self):
        while not self.exit:
            if self.socket.poll(timeout=500):
                request = self.socket.recv_json()
                reply = self.handle_request(request)
                self.socket.send_json(reply)
            self.idle()
        self.socket.close()
        log.info('Exorcism successful. Have a nice day.')

    def handle_request(self, request):
        """Handle *request*, return reply."""
        if not isinstance(request, dict):
            return self.error('invalid request: a dictionary is required.')
        command = request.get('command')
        if command not in self.commands:
            log.error('invalid request was %r', request)
            return self.error('invalid request: no or invalid command.')
        log.debug('Received command %r, request %r', command, request)
        return self.commands[command](self, request)

    def idle(self):
        pass

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
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        return pid

    commands = {}


class APIServer(BaseServer):
    def __init__(self, address, context=None):
        super().__init__(address, context)
        # PID -> (command, params...)
        self.children = {}
        set_process_name('borgcubed [main process]')

    def idle(self):
        self.check_schedule()
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
        pid = self.fork()
        if not pid:
            set_process_name('borgcubed [run-job %s]' % job.id)
            executor = JobExecutor(job)
            executor.execute()
            sys.exit(0)
        else:
            self.children[pid] = ('run-job', str(job.id))
            return {
                'success': True,
                'job': str(job.id),
            }

    commands = {
        'initiate-job': cmd_initiate_job,
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
            code = waitres & 0xFF00
            logger = log.debug if code == 0 else log.error
            if signo:
                logger('Child %d exited with code %d on signal %d', pid, code, signo)
            else:
                logger('Child %d exited with code %d', pid, code)
            command, *params = self.children.pop(pid)
            logger('Command was: %s %r', command, params)
            # TODO if command==run-job, ensure Job is marked as failed.


from borg.helpers import get_cache_dir, Manifest
from borg.cache import Cache

import configparser

import subprocess

from borgcube.keymgt import synthesize_client_key, SyntheticManifest
from borgcube.utils import open_repository

from borg.key import PlaintextKey
from borg.item import ArchiveItem

import msgpack

import shlex
import shutil


class JobExecutor:
    def __init__(self, job):
        self.job = job
        self.client = job.client
        self.repository = job.repository
        self.remote_cache_dir = self.find_remote_cache_dir()

    def execute(self):
        self.job.update_state(Job.State.job_created, Job.State.client_preparing)

        self.synthesize_crypto()
        self.transfer_cache()
        self.job.update_state(Job.State.client_preparing, Job.State.client_prepared)

        self.remote_create()
        self.client_cleanup()
        # TODO sync cache
        self.job.update_state(Job.State.client_cleanup, Job.State.done)

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
            subprocess.check_call(('ssh', self.client.connection.remote, 'mkdir', '-p', self.remote_cache_dir + self.repository.id + '/'))
            subprocess.check_call(rsync + (str(job_cache_path) + '/', connstr))
        finally:
            shutil.rmtree(str(job_cache_path))
        log.debug('transfer_cache: chunks cache')
        chunks_cache = cache_path / 'chunks'
        subprocess.check_call(rsync + (str(chunks_cache), connstr))
        log.debug('transfer_cache: done')

    def create_job_cache(self, cache_path):
        if not cache_path.is_dir():
            self.initialize_cache()
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
        with (job_cache_path / 'config').open('w') as fd:
            config.write(fd)

        return job_cache_path

    def remote_create(self):
        connection = self.client.connection

        command_line = [connection.rsh]
        if connection.ssh_identity_file:
            command_line += '-i', connection.ssh_identity_file
        if connection.rsh_options:
            command_line.append(connection.rsh_options)
        command_line.append(connection.remote)
        command_line.append('BORG_CACHE_DIR=' + shlex.quote(self.remote_cache_dir))
        command_line.append(connection.remote_borg)
        command_line.append('create')
        command_line.append(settings.SERVER_LOGIN + ':' + str(self.job.id) + '::' + self.job.archive_name)

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
        command_line += '--compression', config['compression']
        extra_options = config.get('extra_options')
        if extra_options:
            command_line += extra_options,

        log.debug('Built command line: %r', command_line)
        subprocess.check_call(command_line)
        log.debug('remote create finished (success)')
        self.job.refresh_from_db()
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
            log.warning('Disabling archive chunks cache of %s', archives.parent)
            shutil.rmtree(str(archives))
            archives.touch()

    def initialize_cache(self):
        log.info('No cache found, creating one')
        with open_repository(self.repository) as repository:
            manifest, key = Manifest.load(repository)
            with Cache(repository, key, manifest):
                pass
            self.check_archive_chunks_cache()
        log.info('Cache created')

    def find_remote_cache_dir(self):
        remote_cache_dir = (self.client.connection.remote_cache_dir or '.cache/borg/')
        if remote_cache_dir[-1] != '/':
            remote_cache_dir += '/'
        log.debug('remote_cache_dir is %r', remote_cache_dir)
        return remote_cache_dir
