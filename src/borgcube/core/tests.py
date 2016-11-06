
from subprocess import check_call

import pytest

from .models import Client, ClientConnection, Job, Repository


@pytest.fixture
def client_connection(db):
    return ClientConnection.objects.create(remote='root@testhost')


@pytest.fixture
def client(client_connection):
    return Client.objects.create(
        hostname='testhost',
        name='testhost',
        connection=client_connection
    )


@pytest.fixture
def borg_passphrase():
    return {'BORG_PASSPHRASE': 'abcdef'}


@pytest.fixture
def borg_repo(tmpdir, borg_passphrase):
    path = str(tmpdir.join('repository'))
    check_call(('borg', 'init', '-e=repokey', path,), env=borg_passphrase)
    return path


@pytest.fixture
def repository(db, borg_repo):
    return Repository.objects.create(
        id=b'1' * 32,  # TODO Repository create_from_existing or so
        name='testrepo',
        url=borg_repo,
    )


@pytest.fixture
def job(client, repository):
    return Job.objects.create(
        repository=repository,
        client=client,
    )
