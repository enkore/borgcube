
from borgcube.utils import data_root
from django.http import Http404
from django.http import HttpResponse


def trigger(request, trigger_id):
    # This is a URL-based view, since it can be called anonymously (I plan to make everything
    # publisher-based authenticated-only).
    try:
        trig = data_root().trigger_ids[trigger_id]
    except KeyError:
        raise Http404
    # Depending on the security framework that'll be used (I'm atm mainly considering Yosai),
    # this might become unnecessary. (TODO/SEC)
    trig.run(access_context='anonymous-web')
    return HttpResponse()
