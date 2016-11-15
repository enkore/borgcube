import os
from datetime import datetime

import pytest

from borg.archive import Archive
from borg.cache import Cache
from borg.helpers import Manifest, Location
from borg.logger import setup_logging
from borg.repository import Repository

from . import ReverseRepositoryProxy
from ..core.models import BackupJob
from ..core.tests import backup_job, repository, client, client_connection, borg_repo, borg_passphrase

from ..daemon.backupjob import BackupJobExecutor

setup_logging()


@pytest.fixture
def rrp(backup_job, monkeypatch, borg_passphrase):
    rrp = ReverseRepositoryProxy()
    rrp._location = Location('ssh://test@localhost/%s' % backup_job.id)

    monkeypatch.setenv(*list(borg_passphrase.items())[0])
    BackupJobExecutor.synthesize_crypto(backup_job)
    monkeypatch.setenv(*list(borg_passphrase.items())[0])
    backup_job.force_state(backup_job.State.client_prepared)
    rrp.id = rrp.open(str(backup_job.id).encode())
    rrp.id_str = rrp.id.hex()
    return rrp


def test_invalid_delete(rrp):
    with pytest.raises(ValueError):
        rrp.delete(b'1' * 32)


def test_load_key(rrp):
    key_data = rrp.load_key()
    assert key_data
    assert key_data != rrp.repository.load_key()


def test_manifest_clean(rrp, monkeypatch):
    monkeypatch.delenv('BORG_PASSPHRASE')
    manifest, key = Manifest.load(rrp)
    assert not manifest.archives


def test_manifest_invalid_archive(rrp, monkeypatch):
    monkeypatch.delenv('BORG_PASSPHRASE')
    manifest, key = Manifest.load(rrp)
    manifest.archives['1234 not allowed'] = bytes(32), datetime.now()
    with pytest.raises(ValueError) as exc_info:
        manifest.write()
    assert exc_info.match('illegal archive push')


def test_connection_finalization(rrp, monkeypatch, tmpdir):
    monkeypatch.delenv('BORG_PASSPHRASE')
    monkeypatch.setenv('BORG_CACHE_DIR', tmpdir.join('client-cache'))
    manifest, key = Manifest.load(rrp)
    with Cache(rrp, key, manifest) as cache:
        archive = Archive(rrp, key, manifest, rrp.job.archive_name, cache, create=True)
        archive.write_checkpoint()
        archive.save()
    with pytest.raises(ValueError) as exc_info:
        rrp.get(bytes(32))
    assert exc_info.match('Transaction was doomed. Refusing to continue.')


def test_doom(rrp):
    with pytest.raises(Exception):
        rrp.put(b'1234', b'')
    with pytest.raises(ValueError) as exc_info:
        rrp.get(b'1234' * 8)
    assert exc_info.match('Transaction was doomed by previous exception. Refusing to continue.')
