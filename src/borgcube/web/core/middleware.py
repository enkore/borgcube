import logging

from django.http import HttpResponseServerError

import transaction
from ZODB.POSException import StorageError

log = logging.getLogger(__name__)


def transaction_middleware(get_response):
    """
    Calls `transaction.abort()` before and after obtaining a response.
    """
    def middleware(request):
        transaction.abort()
        response = get_response(request)
        transaction.abort()
        return response
    return middleware


class ZODBErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, StorageError):
            msg = 'Database error: %s: %s' % (type(exception).__name__, exception)
            log.error(msg)
            return HttpResponseServerError(msg)
