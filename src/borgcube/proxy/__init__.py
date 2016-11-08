import functools
import logging
import re
from binascii import unhexlify

import msgpack

from borg.helpers import bin_to_hex, IntegrityError, Manifest
from borg.repository import Repository
from borg.remote import RemoteRepository, RepositoryServer, PathNotAllowed
from borg.cache import Cache
from borg.item import ArchiveItem

from ..core.models import Job
from ..keymgt import SyntheticRepoKey, synthesize_client_key, SyntheticManifest

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
        try:
            self.job = Job.objects.get(pk=path.decode())
        except (Job.DoesNotExist, ValueError):
            raise PathNotAllowed(path)

        self.job.update_state(previous=Job.State.client_prepared, to=Job.State.client_in_progress)

        log.info('Opening repository for job %s', self.job.pk)
        location = self.job.repository.location
        self._real_open(location)
        self._load_repository_key()
        self._load_client_key()
        self._load_cache()
        self._got_archive = False
        self._final_archive = False
        log.debug('Repository ID is %r', self.job.repository.id)
        return unhexlify(self.job.repository.id)

    @property
    def _checkpoint_archives(self):
        return self.job.data.get('checkpoint-archives', [])

    def _add_checkpoint(self, name):
        # XXX TODO does this work? Test!
        self._checkpoint_archives.append(name)
        self.job.save()

    def _real_open(self, location):
        if location.proto == 'ssh':
            # TODO construct & pass args for stuff like umask and remote-path
            self.repository = RemoteRepository(location, exclusive=True)
        else:
            self.repository = Repository(location.path, exclusive=True)
        # RepositoryServer.serve() handles this
        self.repository.__enter__()

    def _load_repository_key(self):
        self._manifest, self._repository_key = Manifest.load(self.repository)

    def _load_client_key(self):
        try:
            key_data = self.job.data['client_key_data']
        except KeyError:
            # Plaintext key
            log.debug('No synthesized client key found - it\'s PlaintextKey')
            self._client_key = synthesize_client_key(self._repository_key, self.repository)
        else:
            log.debug('Loading synthesized client key')
            self._client_key = SyntheticRepoKey.from_data(key_data, self.repository)
        self._client_manifest = SyntheticManifest.load(unhexlify(self.job.data['client_manifest_data']), self._client_key)
        log.debug('Loaded key and manifest')

    def _load_cache(self):
        self._cache = Cache(self.repository, self._repository_key, self._manifest, lock_wait=1)
        self._cache.__enter__()
        self._cache.begin_txn()
        log.debug('Loaded cache')

    def load_key(self):
        log.debug('Client requested repokey')
        return self._client_key.get_key_data()

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
    def get(self, id_):
        repo_data = self.repository.get(id_)
        client_data = self._repo_to_client(id_, repo_data)
        return client_data

    @doom_on_exception()
    def get_many(self, ids, is_preloaded=False):
        for id, repo_data in zip(ids, self.repository.get_many(ids, is_preloaded)):
            yield self._repo_to_client(id, repo_data)

    @doom_on_exception()
    def put(self, id, client_data, wait=True):
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
        # TODO: _checkpoint_archives must be built from ALL archives in the repo... or does it?
        # TODO: we control archive names. if we abort, we won't use the same archive name again.
        if id not in self._checkpoint_archives:
            raise ValueError('BorgCube: illegal delete(id=%s), not a checkpoint archive ID', bin_to_hex(id))
        self.repository.delete(id, wait)
        self._cache.chunks.decref(id)
        assert not self._cache.seen_chunk(id)
        del self._cache.chunks[id]

    @doom_on_exception()
    def rollback(self):
        self.job.update_state(Job.State.client_in_progress, Job.State.failed)
        log.error('Job failed due to client rollback.')
        self._doomed = True
        self.repository.rollback()

    @doom_on_exception()
    def commit(self, save_space=False):
        if not self._got_archive:
            raise ValueError('BorgCube: Cannot commit without adding the archive we wanted')
        log.debug('Client initiated commit')
        if self._final_archive:
            log.debug('Commit for the finalised archive, committing server cache, and not accepting further modifications.')
            self._cache.commit()
            self._cache.close()
            self._cache = None
            self._doomed = True
        self.repository.commit(save_space)

    def _manifest_repo_to_client(self):
        return self._client_manifest.write()

    def _manifest_client_to_repo(self, data):
        try:
            client_manifest = SyntheticManifest.load(data, self._client_key)
        except Exception as exc:
            log.error('Error on client manifest load: %s', exc)
            raise

        for archive_info in client_manifest.archives.list():
            # Don't use list(prefix=...) to catch these explicitly.
            self._process_client_archive_info(archive_info)

    def _process_client_archive_info(self, archive_info):
        if not archive_info.name.startswith(self.job.archive_name):
            log.error('Client tried to push invalid archive %r (id=%s) to repository. Aborting.', archive_info.name, bin_to_hex(archive_info.id))
            raise ValueError('BorgCube: illegal archive push %r', archive_info.name)

        log.debug('Adding archive %r (id %s)', archive_info.name, bin_to_hex(archive_info.id))

        checkpoint_re = re.escape(self.job.archive_name) + r'\.checkpoint(\d+)?'
        if re.fullmatch(checkpoint_re, archive_info.name):
            log.debug('%r is a checkpoint - remembering that', archive_info.name)
            self._add_checkpoint(archive_info.name)
        else:
            log.debug('%r is the finalised archive', archive_info.name)
            self._final_archive = True

        if not self._cache_sync_archive(archive_info.id):
            log.error('Failed to synchronize archive %r into cache (see above), aborting.', archive_info.name)
            raise ValueError('BorgCube: cache sync failed')

        # TODO additional sanitation?
        self._manifest.archives[archive_info.name] = archive_info.id, archive_info.ts
        log.info('Added archive %r (id=%s) to repository.', archive_info.name, bin_to_hex(archive_info.id))
        self._got_archive = True

    def _cache_sync_archive(self, archive_id):
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
        return True
