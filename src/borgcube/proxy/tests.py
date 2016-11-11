import os

import pytest

from borg.helpers import Manifest
from borg.logger import setup_logging

from . import ReverseRepositoryProxy
from ..core.models import BackupJob
from ..core.tests import backup_job, repository, client, client_connection, borg_repo, borg_passphrase

from ..daemon.backupjob import BackupJobExecutor

setup_logging()


@pytest.fixture
def rrp(backup_job, monkeypatch, borg_passphrase):
    rrp = ReverseRepositoryProxy()

    monkeypatch.setenv(*list(borg_passphrase.items())[0])
    BackupJobExecutor.synthesize_crypto(backup_job)
    monkeypatch.setenv(*list(borg_passphrase.items())[0])
    backup_job.force_state(backup_job.State.client_prepared)
    rrp.open(str(backup_job.id).encode())
    return rrp


@pytest.fixture
def proxied_remote(rrp):
    pass


def test_invalid_delete(rrp):
    with pytest.raises(ValueError):
        rrp.delete(b'1' * 32)


def test_load_key(rrp):
    key_data = rrp.load_key()
    assert key_data
    assert key_data != rrp.repository.load_key()


def test_manifest_clean(rrp, proxied_remote):
    # manifest, key = Manifest.load(rrp)
    pass

