import configparser
import logging
import shlex
import shutil
from pathlib import Path
from subprocess import check_call, CalledProcessError

from django.conf import settings

from borg.helpers import get_cache_dir, bin_to_hex, Manifest, Location
from borg.cache import Cache
from borg.key import PlaintextKey
from borg.repository import Repository
from borg.locking import LockTimeout, LockFailed, LockError, LockErrorT

from borgcube.core.models import BackupJob, JobConfig
from borgcube.keymgt import synthesize_client_key, SyntheticManifest
from borgcube.utils import open_repository, tee_job_logs
from django.core.exceptions import ObjectDoesNotExist

from .hookspec import JobExecutor

log = logging.getLogger('borgcubed.backupjob')


def borgcubed_startup(apiserver):
    for job in BackupJob.objects.exclude(db_state__in=[s.value for s in BackupJob.State.STABLE]):
        job.set_failure_cause('borgcubed-restart')
    for job in BackupJob.objects.filter(db_state=BackupJob.State.job_created.value):
        apiserver.queue_job(job)


def borgcubed_job_executor(job_id):
    if BackupJob.objects.filter(id=job_id).exists():
        return BackupJobExecutor


def borgcubed_job_exit(apiserver, job_id, exit_code, signo):
    try:
        job = BackupJob.objects.get(id=job_id)
    except ObjectDoesNotExist:
        return
    if exit_code or signo:
        job.force_state(BackupJob.State.failed)


def borgcubed_handle_request(apiserver, request):
    if request['command'] != 'initiate-backup-job':
        return
    try:
        client_hostname = request['client']
        jobconfig_id = request['job_config']
    except KeyError as ke:
        return apiserver.error('Missing parameter %r', ke.args[0])
    try:
        job_config = JobConfig.objects.get(client=client_hostname, id=jobconfig_id)
    except ObjectDoesNotExist:
        return apiserver.error('No such JobConfig')
    job = BackupJob.objects.create(
        repository=job_config.repository,
        config=job_config,
        client=job_config.client
    )
    log.info('Created job %s for client %s, job config %d', job.id, job_config.client.hostname, job_config.id)
    apiserver.queue_job(job)
    return {
        'success': True,
        'job': str(job.id),
    }


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
    def can_run(cls, job_id):
        job = BackupJob.objects.get(id=job_id)
        blocking_jobs = BackupJob.objects.filter(repository=job.repository).exclude(db_state__in=[s.value for s in BackupJob.State.STABLE])
        job_is_blocked = blocking_jobs.exists()
        if job_is_blocked:
            log.debug('Job %s blocked by running jobs: %s', job_id, ' '.join('{} ({})'.format(job.id, job.db_state) for job in blocking_jobs))
        return not job_is_blocked

    @classmethod
    def prefork(cls, job_id):
        job = BackupJob.objects.get(id=job_id)
        job.update_state(BackupJob.State.job_created, BackupJob.State.client_preparing)

    @classmethod
    def run(cls, job_id):
        job = BackupJob.objects.get(id=job_id)
        executor = cls(job)
        executor.execute()

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
            self.job.update_state(BackupJob.State.client_preparing, BackupJob.State.client_prepared)

            self.remote_create()
            self.client_cleanup()
            self.job.update_state(BackupJob.State.client_cleanup, BackupJob.State.done)
            log.info('Job %s completed successfully', self.job.id)
        except CalledProcessError as cpe:
            self.job.force_state(BackupJob.State.failed)
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
        except RepositoryIDMismatch as id_mismatch:
            repo, db = id_mismatch.args
            self.job.set_failure_cause('repository-id-mismatch', repository_id=repo, saved_id=db)
            log.error('Job %s failed because the stored repository ID (%s) doesn\'t match the real repository ID (%s)', self.job, repo, db)

    def analyse_job_process_error(self, called_process_error):
        if cpe_means_connection_failure(called_process_error):
            self.job.set_failure_cause('client-connection-failed', command=called_process_error.cmd, exit_code=called_process_error.returncode)
            log.error('Job %s failed due to client connection failure', self.job.id)
            return True
        return False

    def synthesize_crypto(self):
        with open_repository(self.repository) as repository:
            if bin_to_hex(repository.id) != self.repository.repository_id:
                raise RepositoryIDMismatch(bin_to_hex(repository.id), self.repository.repository_id)
            manifest, key = Manifest.load(repository)
            client_key = synthesize_client_key(key, repository)
            if not isinstance(client_key, PlaintextKey):
                self.job.data['client_key_data'] = client_key.get_key_data()

            client_manifest = SyntheticManifest(client_key)
            self.job.data['client_manifest_data'] = bin_to_hex(client_manifest.write())
            self.job.data['client_manifest_id_str'] = client_manifest.id_str
            self.job.save()

    def transfer_cache(self):
        cache_path = Path(get_cache_dir()) / self.repository.repository_id
        log.debug('transfer_cache: local cache is %r', cache_path)
        job_cache_path = self.create_job_cache(cache_path)

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
        chunks_cache = cache_path / 'chunks'
        check_call(rsync + (str(chunks_cache), connstr))
        check_call(('ssh', self.client.connection.remote, 'touch', remote_dir + 'files'))
        log.debug('transfer_cache: done')

    def create_job_cache(self, cache_path):
        self.ensure_cache(cache_path)
        job_cache_path = cache_path / str(self.job.id)
        job_cache_path.mkdir()
        log.debug('create_job_cache: path is %r', job_cache_path)

        (job_cache_path / 'chunks.archive.d').touch()
        with (job_cache_path / 'README').open('w') as fd:
            fd.write('This is a Borg cache')
        config = configparser.ConfigParser(interpolation=None)
        config.add_section('cache')
        config.set('cache', 'version', '1')
        config.set('cache', 'repository', self.repository.repository_id)
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
        log.debug('%s', ' '.join(command_line))
        try:
            check_call(command_line)
        except CalledProcessError as cpe:
            if cpe.returncode == 1:
                log.debug('remote create finished (warning)')
                self.job.refresh_from_db()
                self.job.data['borg_warning'] = True
                self.job.save()
            else:
                raise
        else:
            self.job.refresh_from_db()
            log.debug('remote create finished (success)')
        self.job.repository.refresh_from_db()
        self.job.update_state(BackupJob.State.client_in_progress, BackupJob.State.client_done)

    def client_cleanup(self):
        self.job.update_state(BackupJob.State.client_done, BackupJob.State.client_cleanup)
        # TODO delete checkpoints

        # TODO do we actually want this? if we leave the cache, the next job has a good chance of rsyncing just a delta
        # TODO perhaps a per-client setting, to limit space usage on the client with multiple repositories.

    def check_archive_chunks_cache(self):
        archives = Path(get_cache_dir()) / self.repository.repository_id / 'chunks.archive.d'
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