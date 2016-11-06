
class MenuBarMiddleware(object):
    def __init__(self, get_response):
        self.__call__ = get_response

    @lru_cache()
    def menu_modifiers(self):
        return list(map(import_string, getattr(settings, 'MENU', [])))

    def get_menu(self, request):
        menu = []
        for modifier in self.menu_modifiers():
            modifier(request, menu)
        return menu

    def is_active_menu_entry(self, resolver_match, menu_entry):
        is_current_view = (resolver_match.func == menu_entry['view'] or
                           resolver_match.view_name == menu_entry['view'])
        view_args_match = (resolver_match.args == menu_entry.get('args', ()) and
                           resolver_match.kwargs == menu_entry.get('kwargs', {}))
        return is_current_view and view_args_match

    def set_active_menu_entry(self, request, menu):
        resolver_match = request.resolver_match
        for menu_entry in menu:
            if 'url' in menu_entry:
                # An external link cannot be active, since it's not on our site.
                # It's also not view based, so no reverse()ing is needed.
                continue
            menu_entry['active'] = self.is_active_menu_entry(resolver_match, menu_entry)
            menu_entry['url'] = reverse(menu_entry['view'], args=menu_entry.get('args'),
                                        kwargs=menu_entry.get('kwargs'))

    def process_template_response(self, request, response):
        menu = self.get_menu(request)
        self.set_active_menu_entry(request, menu)
        if not response.context_data:
            response.context_data = {}
        response.context_data.setdefault('theme', {})['menu'] = menu

        return response