import transaction

from borgcube import utils
from django.urls import reverse


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

    def process_menu_items(self, items):
        for item in items:
            self.process_menu_items(item.setdefault('items', []))
            try:
                item['url'] = reverse(item['view'])
            except KeyError:
                pass

    def process_template_response(self, request, response):
        try:
            context = response.context_data
            context.pop('management')
        except (AttributeError, KeyError):
            return response

        context['management'] = nav = []
        utils.hook.borgcube_web_management_nav(nav=nav)
        self.process_menu_items(nav)
        return response
