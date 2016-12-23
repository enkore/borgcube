
import os
import logging

from borg.helpers import Manifest
from borg.key import PlaintextKey, RepoKey, Blake2RepoKey, Blake2KeyfileKey, AuthenticatedKey, KeyfileKey, Passphrase

log = logging.getLogger(__name__)


class FakeRepository:
    # We isolate this, so that we can't miss anything in Borg's key logic.

    def __init__(self, repository):
        self.id = repository.id
        self.id_str = repository.id_str

    def get_free_nonce(self):
        return 0

    def commit_nonce_reservation(self, next_unreserved, start_nonce):
        pass


class SyntheticRepoKeyMixin:
    def get_key_data(self) -> str:
        return self._save(Passphrase(''))

    def coerce_chunk_ids(self, coerce_to):
        self.chunk_seed = coerce_to.chunk_seed
        self.id_key = coerce_to.id_key

    def load(self, target, passphrase):
        raise NotImplementedError

    def save(self, target, passphrase):
        pass

    @classmethod
    def from_data(cls, data, repository):
        key = cls(FakeRepository(repository))
        assert key._load(data, Passphrase(''))
        key.init_ciphers()
        return key


class SyntheticRepoKey(SyntheticRepoKeyMixin, RepoKey):
    synthetic_type = 'synthetic-repokey'


class SyntheticBlake2RepoKey(SyntheticRepoKeyMixin, AuthenticatedKey):
    # Any BLAKE2 repository key gets converted into an AuthenticatedKey for the client; the client
    # doesn't do any encryption in this case.
    synthetic_type = 'synthetic-authenticated-blake2'


def synthetic_key_from_data(data, type, repository):
    if type == SyntheticRepoKey.synthetic_type:
        return SyntheticRepoKey.from_data(data, repository)
    elif type == SyntheticBlake2RepoKey.synthetic_type:
        return SyntheticBlake2RepoKey.from_data(data, repository)
    else:
        raise ValueError('Invalid synthetic key type: %r' % type)


def synthesize_client_key(id_key_from, repository):
    if isinstance(id_key_from, PlaintextKey):
        return PlaintextKey(repository)

    assert id_key_from.TYPE in (RepoKey.TYPE, KeyfileKey.TYPE, Blake2RepoKey.TYPE, Blake2KeyfileKey.TYPE, AuthenticatedKey.TYPE), \
        'Unknown key type %s' % type(id_key_from).__name__

    os.environ['BORG_PASSPHRASE'] = ''
    if id_key_from.TYPE in (RepoKey.TYPE, KeyfileKey.TYPE):
        SyntheticClass = SyntheticRepoKey
    else:
        SyntheticClass = SyntheticBlake2RepoKey
    synthetic_key = SyntheticClass.create(FakeRepository(repository), None)
    del os.environ['BORG_PASSPHRASE']
    synthetic_key.coerce_chunk_ids(id_key_from)
    return synthetic_key


class SyntheticManifest(Manifest):
    class ManifestRepository:
        def __init__(self, data=None, repository_id=None):
            self.data = data
            self.id = repository_id

        def get(self, id_):
            assert id_ == Manifest.MANIFEST_ID
            return self.data

        def put(self, id_, data):
            assert id_ == Manifest.MANIFEST_ID
            self.data = data

    def __init__(self, key, repository_id, item_keys=None):
        super().__init__(key, self.ManifestRepository(repository_id=repository_id), item_keys)

    def write(self):
        super().write()
        return self.repository.data

    @classmethod
    def load(cls, data, key, repository_id):
        repository = cls.ManifestRepository(data, repository_id)
        return super().load(repository, key)[0]
