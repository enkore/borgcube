
from django.utils.translation import ugettext_lazy as _

from borgcube.core.models import Trigger
from borgcube.utils import data_root

from . import Publisher, PublisherMenu, ExtendingPublisher


class TriggerManagementPublisher(Publisher, PublisherMenu):
    companion = 'trigger_ids'
    menu_text = _('Trigger')

    def view(self, request):
        pass


class TriggerPublisher(ExtendingPublisher):
    companion = 'trigger'
    menu_text = _('Trigger')

    def view(self, request):
        return self.render(request, 'core/trigger/list.html', {})


def borgcube_web_children(publisher, children):
    if publisher.name == 'management':
        return {
            'trigger': TriggerManagementPublisher(data_root().trigger_ids),
        }
    if isinstance(getattr(publisher.get_companion(), 'trigger', None), Trigger):
        return {
            'trigger': TriggerPublisher(publisher.get_companion().trigger),
        }
