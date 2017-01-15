import logging

from django.http import HttpResponseServerError
from django.urls import reverse

import transaction
from ZODB.POSException import StorageError

from borgcube import utils
from borgcube.web.core.views import RootPublisher

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


class SidebarMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_template_response(self, request, response):
        try:
            context = response.context_data
            context.pop('management')
        except (AttributeError, KeyError):
            return response

        mp = RootPublisher(utils.data_root()).resolve(['management']).__self__

        def construct(pub):
            try:
                descend = pub.menu_descend
            except AttributeError:
                descend = False
            if not descend:
                return
            item = {
                'text': pub.menu_text,
                'url': pub.reverse(),
                'items': [],
            }
            for pub in pub.children().values():
                subitem = construct(pub)
                if subitem:
                    item['items'].append(subitem)
            return item

        context['management'] = construct(mp)['items']

        return response


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
