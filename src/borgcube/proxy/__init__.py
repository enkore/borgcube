import functools
import logging
import re
from binascii import unhexlify

import msgpack

import transaction

from borg.archive import Archive as BorgArchive
from borg.helpers import bin_to_hex, IntegrityError, Manifest
from borg.repository import Repository
from borg.remote import RepositoryServer, PathNotAllowed
from borg.cache import Cache
from borg.item import ArchiveItem

from ..core.models import Archive
from ..job.backup import BackupJob
from ..keymgt import synthetic_key_from_data, synthesize_client_key, SyntheticManifest
from ..utils import set_process_name, open_repository, data_root

log = logging.getLogger(__name__)
# TODO per job log file, the log from this process should not get to the connected client


def doom_on_exception(exc_whitelist=(Repository.ObjectNotFound, IntegrityError)):
    def decorator(proxy_method):
        @functools.wraps(proxy_method)
        def wrapper(self, *args, **kwargs):
            if getattr(self, '_doomed_by_exception', False):
                raise ValueError('Transaction was doomed by previous exception. Refusing to continue.')
            if getattr(self, '_doomed', False):
                raise ValueError('Transaction was doomed. Refusing to continue.')
            try:
                return proxy_method(self, *args, **kwargs)
            except Exception as exc:
                if not isinstance(exc, exc_whitelist):
                    self._doomed_by_exception = True
                raise
        return wrapper
    return decorator


class ReverseRepositoryProxy(RepositoryServer):
    rpc_methods = (
        '__len__',
        # 'check',
        'commit',
        'delete',
        # 'destroy',
        'get',
        # 'list',
        # 'scan',
        'negotiate',
        'open',
        'put',
        'rollback',
        # 'save_key',
        'load_key',
        # 'break_lock',
        'get_free_nonce',
        'commit_nonce_reservation'
    )

    _cache = None

    def __init__(self, restrict_to_paths=(), append_only=False):
        super().__init__(restrict_to_paths, append_only)

    def serve(self):
        try:
            super().serve()
        finally:
            if self._cache:
                self._cache.close()

    @doom_on_exception()
    def open(self, path, create=False, lock_wait=None, lock=True, exclusive=None, append_only=False):
        if create:
            raise ValueError('BorgCube: illegal open(create=True)')
        log.debug('ReverseRepositoryProxy lock_wait=%s, lock=%s, exclusive=%s, append_only=%s, path=%r',
                  lock_wait, lock, exclusive, append_only, path)

        self.job = self._get_job(path)
        self.job.update_state(previous=BackupJob.State.client_prepared, to=BackupJob.State.client_in_progress)
        set_process_name('borgcube-proxy [job %s]' % self.job.id)

        log.info('Opening repository for job %s', self.job.id)
        self._real_open()
        self._load_repository_key()
        self._load_client_key()
        self._load_cache()
        self._got_archive = False
        self._final_archive = False
        log.debug('Repository ID is %r', self.job.repository.repository_id)
        return unhexlify(self.job.repository.repository_id)

    def _get_job(self, path):
        try:
            path = path.decode()
        except ValueError:
            raise PathNotAllowed(path)

        for job in data_root().jobs_by_state[BackupJob.State.client_prepared].values():
            if job.reverse_path == path:
                return job
        else:
            raise PathNotAllowed(path)

    def _real_open(self):
        self.repository = open_repository(self.job.repository)
        # RepositoryServer.serve() handles this
        self.repository.__enter__()

    def _load_repository_key(self):
        self._manifest, self._repository_key = Manifest.load(self.repository)

    def _load_client_key(self):
        try:
            key_data = self.job.client_key_data
        except AttributeError:
            # Plaintext key
            log.debug('No synthesized client key found - it\'s PlaintextKey')
            self._client_key = synthesize_client_key(self._repository_key, self.repository)
        else:
            synthetic_type = self.job.client_key_type
            log.debug('Loading synthesized client key (%s)', synthetic_type)
            self._client_key = synthetic_key_from_data(key_data, synthetic_type, self.repository)
        self._client_manifest = SyntheticManifest.load(unhexlify(self.job.client_manifest_data), self._client_key, self.repository.id)
        self._first_manifest_read = True
        assert self._client_manifest.id_str == self.job.client_manifest_id_str
        log.debug('Loaded client key and manifest')

    def _load_cache(self):
        self._cache = Cache(self.repository, self._repository_key, self._manifest, lock_wait=1)
        self._cache.__enter__()
        self._cache.begin_txn()
        log.debug('Loaded cache')

    def _add_checkpoint(self, id):
        self.job.checkpoint_archives.append(bin_to_hex(id))
        transaction.get().note('Added checkpoint archive %s for job %s' % (bin_to_hex(id), self.job.id))
        transaction.commit()

    def get_free_nonce(self):
        """API"""
        return 0

    def commit_nonce_reservation(self, next_unreserved, start_nonce):
        """API"""

    def load_key(self):
        """API"""
        log.debug('Client requested repokey')
        # Note: the .encode() is technically not necessary as msgpack would turn it into ASCII-bytes anyway,
        #       but it makes testing easier, since it doesn't need to rely on that implementation detail.
        return self._client_key.get_key_data().encode('ascii')

    def _repo_to_client(self, id, repo_data):
        if id == Manifest.MANIFEST_ID:
            client_data = self._manifest_repo_to_client()
        else:
            try:
                client_plaintext_chunk = self._repository_key.decrypt(id, repo_data)
            except IntegrityError as ie:
                log.error('Integrity error on repo decryption: %s', ie)
                raise
            client_data = self._client_key.encrypt(client_plaintext_chunk)
        return client_data

    @doom_on_exception()
    def get(self, id):
        """API"""
        repo_data = self.repository.get(id)
        client_data = self._repo_to_client(id, repo_data)
        return client_data

    @doom_on_exception()
    def get_many(self, ids, is_preloaded=False):
        """API"""
        for id, repo_data in zip(ids, self.repository.get_many(ids, is_preloaded)):
            yield self._repo_to_client(id, repo_data)

    @doom_on_exception()
    def put(self, id, data, wait=True):
        """API"""
        client_data = data
        is_manifest = id == Manifest.MANIFEST_ID
        try:
            if is_manifest:
                repo_plaintext_chunk = self._manifest_client_to_repo(client_data)
            else:
                client_plaintext_chunk = self._client_key.decrypt(id, client_data)
                repo_plaintext_chunk = client_plaintext_chunk
        except IntegrityError as ie:
            log.error('Integrity error on client decryption: %s', ie)
            raise

        if is_manifest:
            self._manifest.write()
        else:
            # TODO Don't recompress.
            # "Trust" the compressed chunk after the chunk ID validated.
            repo_data = self._repository_key.encrypt(repo_plaintext_chunk)
            self.repository.put(id, repo_data, wait)

    @doom_on_exception()
    def delete(self, id, wait=True):
        """API"""
        if bin_to_hex(id) not in self.job.checkpoint_archives:
            raise ValueError('BorgCube: illegal delete(id=%s), not a checkpoint archive ID', bin_to_hex(id))
        self.repository.delete(id, wait)
        self._cache.chunks.decref(id)
        assert not self._cache.seen_chunk(id)
        del self._cache.chunks[id]

    @doom_on_exception()
    def rollback(self):
        """API"""
        self.job.update_state(BackupJob.State.client_in_progress, BackupJob.State.failed)
        log.error('Job failed due to client rollback.')
        self._doomed = True
        self._cache.close()
        self.repository.rollback()

    def _add_completed_archive(self):
        log.debug('Saving archive metadata to database')
        archive = BorgArchive(self.repository, self._repository_key, self._manifest, self.job.archive_name, cache=self._cache)
        stats = archive.calc_stats(self._cache)
        duration = archive.ts_end - archive.ts
        ao = Archive(
            id=archive.fpr,
            repository=self.job.repository,
            name=archive.name,
            client=self.job.client,
            job=self.job,
            nfiles=stats.nfiles,
            original_size=stats.osize,
            compressed_size=stats.csize,
            deduplicated_size=stats.usize,
            duration=duration,
            timestamp=archive.ts,
            timestamp_end=archive.ts_end,
        )
        self.job.archive = ao
        transaction.get().note('Added completed archive %s for job %s' % (ao.id, self.job.id))
        transaction.commit()
        log.debug('Saved archive metadata')

    @doom_on_exception()
    def commit(self, save_space=False):
        """API"""
        if not self._got_archive:
            raise ValueError('BorgCube: Cannot commit without adding the archive we wanted')
        log.debug('Client initiated commit')
        if self._final_archive:
            log.debug('Commit for the finalised archive, committing server cache, and not accepting further modifications.')
            self._cache.commit()
            self._add_completed_archive()
            self._cache.close()
            self._cache = None
            self._doomed = True
        self.repository.commit(save_space)
        log.debug('Repository commit done.')

    def _manifest_repo_to_client(self):
        if self._first_manifest_read:
            self._first_manifest_read = False
            return unhexlify(self.job.client_manifest_data)
        return self._client_manifest.write()

    def _manifest_client_to_repo(self, data):
        try:
            client_manifest = SyntheticManifest.load(data, self._client_key, self.repository.id)
        except Exception as exc:
            log.error('Error on client manifest load: %s', exc)
            raise

        for archive_info in client_manifest.archives.list():
            # Don't use list(prefix=...) to catch these explicitly.
            self._process_client_archive_info(archive_info)

    def _process_client_archive_info(self, archive_info):
        if not archive_info.name.startswith(self.job.archive_name):
            log.error('Client tried to push invalid archive %r (id=%s) to repository. Aborting.', archive_info.name, bin_to_hex(archive_info.id))
            raise ValueError('BorgCube: illegal archive push %r' % archive_info.name)

        log.debug('Adding archive %r (id %s)', archive_info.name, bin_to_hex(archive_info.id))

        checkpoint_re = re.escape(self.job.archive_name) + r'\.checkpoint(\d+)?'
        if re.fullmatch(checkpoint_re, archive_info.name):
            log.debug('%r is a checkpoint - remembering that', archive_info.name)
            self._add_checkpoint(archive_info.id)
        else:
            log.debug('%r is the finalised archive', archive_info.name)
            self._final_archive = True

        if not self._cache_sync_archive(archive_info.id):
            log.error('Failed to synchronize archive %r into cache (see above), aborting.', archive_info.name)
            raise ValueError('BorgCube: cache sync failed')

        # TODO additional sanitation?
        self._manifest.archives[archive_info.name] = archive_info.id, archive_info.ts
        log.info('Added archive %r (id %s) to repository.', archive_info.name, bin_to_hex(archive_info.id))
        self._got_archive = True

    def _cache_sync_archive(self, archive_id):
        log.debug('Started cache sync')
        add_chunk = self._cache.chunks.add
        cdata = self._cache.repository.get(archive_id)
        _, data = self._cache.key.decrypt(archive_id, cdata)
        add_chunk(archive_id, 1, len(data), len(cdata))
        try:
            archive = ArchiveItem(internal_dict=msgpack.unpackb(data))
        except (TypeError, ValueError, AttributeError) as error:
            log.error('Corrupted/unknown archive metadata: %s', error)
            return False
        if archive.version != 1:
            log.error('Unknown archive metadata version %r', archive.version)
            return False
        unpacker = msgpack.Unpacker()
        for item_id, chunk in zip(archive.items, self._cache.repository.get_many(archive.items)):
            _, data = self._cache.key.decrypt(item_id, chunk)
            add_chunk(item_id, 1, len(data), len(chunk))
            unpacker.feed(data)
            for item in unpacker:
                if not isinstance(item, dict):
                    log.error('Error: Did not get expected metadata dict - archive corrupted!')
                    return False
                if b'chunks' in item:
                    for chunk_id, size, csize in item[b'chunks']:
                        add_chunk(chunk_id, 1, size, csize)
        log.debug('Completed cache sync')
        return True
