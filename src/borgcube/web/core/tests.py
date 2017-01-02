from django.urls import reverse

import pytest

import transaction

from borgcube.core.models import Client, RshClientConnection
from . import views


@pytest.fixture
def client_connection():
    with transaction.manager:
        return RshClientConnection(remote='root@testhost')


@pytest.fixture
def client(client_connection):
    with transaction.manager:
        return Client(
            hostname='testhost',
            connection=client_connection
        )


def test_list_clients(rf, client):
    response = views.clients(rf.get(''))
    assert response.status_code == 200
    contents = template_response_contents(response)
    assert 'testhost' in contents
    clients = response.context_data['clients']
    assert list(clients) == [client]


def template_response_contents(tr):
    tr.render()
    return bytes(tr).decode()


def test_view_client(rf, client):
    response = views.client_view(rf.get(''), client.hostname)
    assert response.status_code == 200
    contents = template_response_contents(response)
    assert 'testhost' in contents
    assert 'root@testhost' in contents


def test_edit_client(rf, client):
    response = views.client_edit(rf.get(''), client.hostname)
    assert response.status_code == 200
    template_response_contents(response)

    request = rf.post('', data={
        'connection-remote': 'user@testhost',
        'connection-rsh': client.connection.rsh,
        'connection-remote_borg': client.connection.remote_borg
    })
    response = views.client_edit(request, client.hostname)
    assert response.status_code == 302, template_response_contents(response)
    assert response.url == reverse(views.client_view, args=(client.hostname,))
    assert client.hostname == 'testhost'
    assert client.connection.remote == 'user@testhost'
