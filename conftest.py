
from django.conf import settings

import pytest

from borgcube.utils import configure_plugins, reset_db_connection, data_root


def pytest_configure():
    configure_plugins()


@pytest.yield_fixture(autouse=True)
def clear_db():
    settings.BUILTIN_ZEO = False
    settings.DB_URI = 'memory://'
    data_root()
    yield
    reset_db_connection()
