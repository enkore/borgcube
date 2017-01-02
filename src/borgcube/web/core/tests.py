from datetime import datetime, timedelta

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


class TestCalendarSheet:
    def test_ez(self):
        cs = views.CalendarSheet(datetime(2017, 1, 1, 3, 2, 1))
        assert cs.month == datetime(2017, 1, 1)
        assert cs.month_end == datetime(2017, 2, 1)
        assert cs.sheet_begin == datetime(2016, 12, 26)
        assert cs.sheet_end == datetime(2017, 2, 5)
        assert len(cs.weeks) == 6

        for i in range(6):
            assert cs.weeks[0].days[i].off_month
        for i in range(5):
            assert cs.weeks[5].days[2 + i].off_month

        assert cs.weeks[0].number == 52
        assert cs.weeks[1].number == 1

    def test_exact_last_row(self):
        cs = views.CalendarSheet(datetime(2017, 4, 1))
        assert len(cs.weeks) == 5
        for i in range(7):
            assert not cs.weeks[4].days[i].off_month

    def test_exact_first_row(self):
        cs = views.CalendarSheet(datetime(2017, 5, 1))
        assert len(cs.weeks) == 5
        for i in range(7):
            assert not cs.weeks[0].days[i].off_month

    @pytest.mark.parametrize('day', (
        datetime(2077, 1, 1),
        # 2013-01-01: prevday is 2012-12-30, day is 2013-01-01, between these two is a +1 leap second.
        datetime(2013, 1, 1),
    ))
    def test_days_are_non_overlapping(self, day):
        # Pretty sure that there is at least one mistake lurking around here.
        cs = views.CalendarSheet(day)
        prevday, day, nextday = cs.weeks[0].days[:3]
        assert prevday.end < day.begin
        assert day.end < nextday.begin
        assert (day.begin - prevday.end) == timedelta(microseconds=1)
        assert (nextday.begin - day.end) == timedelta(microseconds=1)
