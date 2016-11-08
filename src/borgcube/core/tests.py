
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


def test_job_state(job):
    assert job.state == Job.State.job_created
    assert job.db_state == 'job-created'
    assert not job.failed


def test_job_update_state(job):
    assert job.state == Job.State.job_created
    job.update_state(Job.State.job_created, Job.State.failed)
    assert job.state == Job.State.failed
    assert job.failed


def test_job_update_state_str(job):
    with pytest.raises(Exception):
        job.update_state(job.state, 'something')
    with pytest.raises(Exception):
        job.update_state('something', job.state)


def test_job_update_state_fail(job):
    with pytest.raises(ValueError):
        job.update_state(Job.State.client_done, Job.State.failed)
    assert job.state == Job.State.job_created


def test_job_force_state(job):
    assert not job.force_state(job.state)
    assert job.force_state(Job.State.failed)
    assert job.state == Job.State.failed


def test_job_archive_name(job):
    assert job.archive_name == 'testhost-%s' % job.id
    assert 'UUID' not in job.archive_name


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
