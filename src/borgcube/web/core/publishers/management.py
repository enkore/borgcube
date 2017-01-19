
from django.utils.translation import ugettext_lazy as _

from . import Publisher, PublisherMenu


class ManagementPublisher(Publisher, PublisherMenu):
    """
    Base class for management publishers (that want to be part of the management area).

    Inherits `PublisherMenu` to enable the menu entry, and uses *management.html* as a
    base_template, which enables the sidebar used for navigation in the management area.
    It also adds the *management* key to the template context which contains the
    actual sidebar navigation.
    """
    def base_template(self, request):
        return 'management.html'

    def context(self, request):
        context = super().context(request)
        context['management'] = self._construct_menu(request)
        return context

    def _construct_menu(self, request):
        mp = request.root.resolve(['management']).__self__

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

        return construct(mp)['items']


class ManagementAreaPublisher(ManagementPublisher):
    """
    Publisher responsible for the /management/ area; it does not publish anything on it's own,
    but is an anchor point for plugins and other parts to add their management functionality.
    """
    name = 'management'
    menu_descend = True
    menu_text = _('Management')

    def view(self, request):
        return self.render(request)
