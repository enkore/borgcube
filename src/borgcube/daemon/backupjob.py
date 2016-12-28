import configparser
import collections
import logging
import shlex
import shutil
import subprocess
from pathlib import Path
from subprocess import CalledProcessError

from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from django import forms

import transaction

from borg.helpers import get_cache_dir, bin_to_hex, Manifest, Location
from borg.cache import Cache
from borg.key import PlaintextKey
from borg.repository import Repository
from borg.locking import LockTimeout, LockFailed, LockError, LockErrorT

from borgcube.core.models import BackupJob, JobConfig, ScheduledAction
from borgcube.keymgt import synthesize_client_key, SyntheticManifest
from borgcube.utils import open_repository, tee_job_logs, data_root
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from .hookspec import JobExecutor

log = logging.getLogger('borgcubed.backupjob')


def check_call(*popenargs, **kwargs):
    kwargs['stdin'] = subprocess.DEVNULL
    return subprocess.check_call(*popenargs, **kwargs)


def borgcubed_job_executor(job):
    if job.short_name == 'backup':
        return BackupJobExecutor


def borgcubed_handle_request(apiserver, request):
    if request['command'] != 'initiate-backup-job':
        return
    try:
        client_hostname = request['client']
        jobconfig_oid = request['job_config']
    except KeyError as ke:
        return apiserver.error('Missing parameter %r', ke.args[0])
    try:
        client = data_root().clients[client_hostname]
        for config in client.job_configs:
            if config.oid == jobconfig_oid:
                break
        else:
            raise KeyError
    except KeyError:
        return apiserver.error('No such JobConfig')
    job = make_backup_job(apiserver, client, config)
    return {
        'success': True,
        'job': job.oid,
    }


def make_backup_job(apiserver, client, config):
    job = BackupJob(
        repository=config.repository,
        client=client,
        config=config,
    )
    transaction.commit()
    log.info('Created job %s for client %s, job config %s', job.oid, client.hostname, config.oid)
    apiserver.queue_job(job)
    return job


def job_configs_as_choices():
    for client in data_root().clients.values():
        for config in client.job_configs:
            yield config.oid, config


class ScheduledBackup(ScheduledAction):
    name = _('Schedule backup job')
    job_config = None

    def __init__(self, schedule, job_config):
        super().__init__(schedule)
        self.job_config = job_config

    def __str__(self):
        return _('Run {}').format(self.job_config)

    def execute(self, apiserver):
        for state, jobs in data_root().jobs_by_state.items():
            if state in BackupJob.State.STABLE - {BackupJob.State.job_created}:
                continue
            for job in jobs.values():
                if job.config == self.job_config:
                    log.warning(
                        'run_from_schedule: not triggering a new job for config %s, since job %s is queued or running',
                        self.job_config.oid, job.oid)
                    return

        make_backup_job(apiserver, self.job_config.client, self.job_config)

    class Form(forms.Form):
        job_config = forms.ChoiceField(choices=job_configs_as_choices)

        def clean(self):
            data = super().clean()
            o = data_root()._p_jar[bytes.fromhex(data['job_config'])]
            if not isinstance(o, JobConfig):
                raise ValidationError('Invalid object reference')
            data['job_config'] = o
            return data


def cpe_means_connection_failure(called_process_error):
    command = called_process_error.cmd[0]
    exit_code = called_process_error.returncode
    rsync_errors = (2, 3, 5, 6, 10, 11, 12, 13, 14, 21, 22, 23, 24, 25, 30, 35)
    # SSH connection error, or rsync error, which is likely also connection related
    return (('ssh' in command and exit_code == 255) or
            ('rsync' in command and exit_code in rsync_errors))


class RepositoryIDMismatch(RuntimeError):
    pass


class BackupJobExecutor(JobExecutor):
    name = 'backup-job'

    @classmethod
    def prefork(cls, job):
        job.update_state(BackupJob.State.job_created, BackupJob.State.client_preparing)

    @classmethod
    def run(cls, job):
        executor = cls(job)
        executor.execute()

    def __init__(self, job):
        tee_job_logs(job)
        self.job = job
        self.client = job.client
        self.repository = job.repository

        self.remote_cache_dir = self.find_remote_cache_dir()
        self.cache_path = Path(get_cache_dir()) / self.repository.repository_id
        log.debug('local cache is %s', self.cache_path)

    def execute(self):
        try:
            self.synthesize_crypto(self.job)
            job_cache_path = self.create_job_cache(self.cache_path)
            self.transfer_cache(job_cache_path)
            self.job.update_state(BackupJob.State.client_preparing, BackupJob.State.client_prepared)

            self.remote_create(self.create_command_line())
            self.client_cleanup()
            self.job.update_state(BackupJob.State.client_cleanup, BackupJob.State.done)
            log.info('Job %s completed successfully', self.job.oid)
        except CalledProcessError as cpe:
            self.job.force_state(BackupJob.State.failed)
            if not self.analyse_job_process_error(cpe):
                raise
        except Repository.DoesNotExist:
            self.job.set_failure_cause('repository-does-not-exist')
            log.error('Job %s failed because the repository %r does not exist', self.job.oid, self.repository.url)
        except Repository.CheckNeeded:
            # TODO: schedule check automatically?
            self.job.set_failure_cause('repository-check-needed')
            log.error('Job %s failed because the repository %r needs a check run', self.job.oid, self.repository.url)
        except Repository.InsufficientFreeSpaceError:
            self.job.set_failure_cause('repository-enospc')
            log.error('Job %s failed because the repository %r had not enough free space', self.job.oid, self.repository.url)
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
        except RepositoryIDMismatch as id_mismatch:
            repo, db = id_mismatch.args
            self.job.set_failure_cause('repository-id-mismatch', repository_id=repo, saved_id=db)
            log.error('Job %s failed because the stored repository ID (%s) doesn\'t match the real repository ID (%s)', self.job, repo, db)

    def analyse_job_process_error(self, called_process_error):
        log.error('%s', called_process_error.stderr)
        log.error('%s', called_process_error.output)
        if cpe_means_connection_failure(called_process_error):
            self.job.set_failure_cause('client-connection-failed', command=called_process_error.cmd, exit_code=called_process_error.returncode)
            log.error('Job %s failed due to client connection failure', self.job.oid)
            return True
        if 'A newer version is required to access this repository.' in called_process_error.output and called_process_error.returncode == 2:
            self.job.set_failure_cause('client-borg-outdated', output=called_process_error.output)
            log.error('Job %s failed because the Borg on the client is too old', self.job)
            return True
        return False

    @staticmethod
    def synthesize_crypto(job):
        with open_repository(job.repository) as repository:
            if bin_to_hex(repository.id) != job.repository.repository_id:
                raise RepositoryIDMismatch(bin_to_hex(repository.id), job.repository.repository_id)
            manifest, key = Manifest.load(repository)
            client_key = synthesize_client_key(key, repository)
            if not isinstance(client_key, PlaintextKey):
                job.client_key_data = client_key.get_key_data()
                job.client_key_type = client_key.synthetic_type

            client_manifest = SyntheticManifest(client_key, repository.id)
            job.client_manifest_data = bin_to_hex(client_manifest.write())
            job.client_manifest_id_str = client_manifest.id_str
            transaction.commit()

    def transfer_cache(self, job_cache_path):
        # TODO per-client files cache, on the client or on the server?
        # TODO rsh, rsh_options
        remote_dir = self.remote_cache_dir + self.repository.repository_id + '/'
        connstr = self.client.connection.remote + ':' + remote_dir
        rsync = ('rsync', '-rI', '--delete', '--exclude', '/files')
        log.debug('transfer_cache: rsync connection string is %r', connstr)
        log.debug('transfer_cache: auxiliary files')
        try:
            check_call(('ssh', self.client.connection.remote, 'mkdir', '-p', remote_dir))
            check_call(rsync + (str(job_cache_path) + '/', connstr))
        finally:
            shutil.rmtree(str(job_cache_path))
        log.debug('transfer_cache: chunks cache')
        chunks_cache = self.cache_path / 'chunks'
        check_call(rsync + (str(chunks_cache), connstr))
        check_call(('ssh', self.client.connection.remote, 'touch', remote_dir + 'files'))
        log.debug('transfer_cache: done')

    def create_job_cache(self, cache_path):
        self.ensure_cache(cache_path)
        job_cache_path = cache_path / str(self.job.oid)
        job_cache_path.mkdir()
        log.debug('create_job_cache: path is %r', job_cache_path)

        (job_cache_path / 'chunks.archive.d').touch()
        with (job_cache_path / 'README').open('w') as fd:
            fd.write('This is a Borg cache')
        config = configparser.ConfigParser(interpolation=None)
        config.add_section('cache')
        config.set('cache', 'version', '1')
        config.set('cache', 'repository', self.repository.repository_id)
        config.set('cache', 'manifest',  self.job.client_manifest_id_str)
        # TODO: path canoniciialailaition thing
        config.set('cache', 'previous_location', Location(self.job.reverse_location).canonical_path().replace('/./', '/~/'))
        with (job_cache_path / 'config').open('w') as fd:
            config.write(fd)

        return job_cache_path

    def callx(self, log_name, command_line):
        def exit():
            exit_code = p.wait()
            if exit_code:
                raise CalledProcessError(exit_code, command_line,
                                         output='\n'.join(stdout_tail),
                                         stderr='\n'.join(stderr_tail))

        stderr_tail = collections.deque(maxlen=100)
        stdout_tail = collections.deque(maxlen=100)
        with subprocess.Popen(command_line, stdout=subprocess.PIPE, stderr=None, stdin=subprocess.DEVNULL, universal_newlines=True) as p:
            try:
                stderr, stdout = p.communicate()
                if not stderr and not stdout:
                    return exit()
                if stderr:
                    for line in stderr.splitlines():
                        log.info('[%s] %s', log_name, line)
                        stderr_tail.append(line)
                if stdout:
                    for line in stdout.splitlines():
                        log.info('[%s] %s', log_name, line)
                        stdout_tail.append(line)
                exit()
            except:
                p.kill()
                p.wait()
                raise

    def create_command_line(self):
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
        command_line.append(self.job.reverse_location + '::' + self.job.archive_name)

        if settings.SERVER_PROXY_PATH:
            command_line += '--remote-path', settings.SERVER_PROXY_PATH

        config = self.job.config
        for path in config.paths:
            command_line.append(shlex.quote(path))
        for exclude in config.excludes:
            command_line += '--exclude', shlex.quote(exclude)
        if config.one_file_system:
            command_line += '--one-file-system',
        if config.read_special:
            command_line += '--read-special',
        if config.ignore_inode:
            command_line += '--ignore-inode',
        command_line += '--checkpoint-interval', str(config.checkpoint_interval)
        command_line += '--compression', config.compression
        extra_options = config.extra_options
        if extra_options:
            command_line += extra_options,

        log.debug('Built command line: %r', command_line)
        log.debug('%s', ' '.join(command_line))
        return command_line

    def remote_create(self, command_line):
        try:
            self.callx('create', command_line)
        except CalledProcessError as cpe:
            if cpe.returncode == 1:
                log.debug('remote create finished (warning)')
                with transaction.manager:
                    self.job.borg_warning = True
            else:
                raise
        else:
            log.debug('remote create finished (success)')
        finally:
            transaction.begin()
        self.job.update_state(BackupJob.State.client_in_progress, BackupJob.State.client_done)

    def client_cleanup(self):
        self.job.update_state(BackupJob.State.client_done, BackupJob.State.client_cleanup)
        # TODO delete checkpoints

        # TODO do we actually want this? if we leave the cache, the next job has a good chance of rsyncing just a delta
        # TODO perhaps a per-client setting, to limit space usage on the client with multiple repositories.

    def check_archive_chunks_cache(self):
        archives = self.cache_path / 'chunks.archive.d'
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
