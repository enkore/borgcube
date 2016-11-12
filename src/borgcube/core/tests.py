
from pathlib import Path
from subprocess import check_call

import pytest

from .models import Client, ClientConnection, BackupJob, Repository, Job


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
    dir = str(tmpdir.join('repository'))
    check_call(('borg', 'init', '-e=repokey', dir,), env=borg_passphrase)
    return Path(dir)


@pytest.fixture
def repository(db, borg_repo):
    with (borg_repo / 'config').open() as fd:
        for line in fd:
            if line.startswith('id = '):
                repository_id = line.split('id =')[1].strip()
                break
    return Repository.objects.create(
        name='testrepo',
        repository_id=repository_id,
        url=str(borg_repo),
    )


@pytest.fixture
def backup_job(client, repository):
    return BackupJob.objects.create(
        repository=repository,
        client=client,
    )


@pytest.fixture
def job(db):
    return Job.objects.create()


def test_job_state(job):
    assert job.state == Job.State.job_created == 'job_created'
    assert not job.failed


def test_job_update_state(job):
    assert job.state == Job.State.job_created
    job.update_state(Job.State.job_created, Job.State.failed)
    assert job.state == Job.State.failed
    assert job.failed


def test_job_update_state_fail(job):
    with pytest.raises(ValueError):
        job.update_state(Job.State.done, Job.State.failed)
    assert job.state == Job.State.job_created


def test_job_force_state(job):
    assert not job.force_state(job.state)
    assert job.force_state(Job.State.failed)
    assert job.state == Job.State.failed


def test_backup_job_archive_name(backup_job):
    assert backup_job.archive_name == 'testhost-%s' % backup_job.id
    assert 'UUID' not in backup_job.archive_name


def test_job_data(job):
    data = job.data
    data['key'] = True
    list = data.setdefault('list', [])
    list.append('string')
    job.save()
    job.refresh_from_db()
    assert job.data['key'] is True
    assert job.data['list'] == ['string']


def test_job_data_refs_int_keys(job):
    job.data['d'] = {}
    job.data['d']['a'] = 1
    job.data['d'].update({1: 2})
    job.save()
    job.refresh_from_db()
    # Take careful note: JSON keys are always strings. non-str keys are converted to a string.
    assert job.data['d'] == {'a': 1, '1': 2}
