
import os
from binascii import unhexlify

from borg.helpers import Manifest, bin_to_hex
from borg.key import PlaintextKey, RepoKey, KeyfileKey, Passphrase

from borg.repository import Repository

class FakeRepository:
    # We isolate this, so that we can't miss anything in Borg's key logic.

    def __init__(self, repository):
        self.id = repository.id
        self.id_str = repository.id_str

    def get_free_nonce(self):
        return 0

    def commit_nonce_reservation(self, next_unreserved, start_nonce):
        pass


class SyntheticRepoKey(RepoKey):
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


def synthesize_client_key(id_key_from, repository):
    if isinstance(id_key_from, PlaintextKey):
        return PlaintextKey(repository)

    assert isinstance(id_key_from, (RepoKey, KeyfileKey)), 'Unknown key type %s' % type(id_key_from).__name__

    os.environ['BORG_PASSPHRASE'] = ''
    synthetic_key = SyntheticRepoKey.create(FakeRepository(repository), None)
    del os.environ['BORG_PASSPHRASE']
    synthetic_key.coerce_chunk_ids(id_key_from)
    return synthetic_key


class SyntheticManifest(Manifest):
    class ManifestRepository:
        def __init__(self, data=None):
            self.data = data

        def get(self, id_):
            assert id_ == Manifest.MANIFEST_ID
            return self.data

        def put(self, id_, data):
            assert id_ == Manifest.MANIFEST_ID
            self.data = data

    def __init__(self, key, repository=None, item_keys=None):
        super().__init__(key, repository or self.ManifestRepository(), item_keys)

    def write(self):
        super().write()
        return self.repository.data

    @classmethod
    def load(cls, data, key):
        repository = cls.ManifestRepository(data)
        return super().load(repository, key)[0]
