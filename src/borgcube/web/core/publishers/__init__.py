import logging
from functools import partial
from urllib.parse import quote as urlquote

from borgcube.utils import hook

from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse

log = logging.getLogger(__name__)


class PublisherMenu:
    menu_descend = True
    menu_text = ''


class Publisher:
    """
    Core class of the object publishing system.

    Since the core of BorgCube is not tied to the web interface, objects do not directly
    implement object publishing protocols like usually done in eg. Zope or Pyramid.

    Instead a second hierarchy of object exists, the *publishers*, that only contain web-
    related functionality. Every publisher instance is bound to a *companion*, the core
    object that it renders. The `companion` attribute defines how the instance attribute
    shall be named.

    A publisher can have multiple views, but by default only has it's default view.

    A publisher can either have a "relatively static" number of children, by implementing
    `children` and returning a mapping of segments to child publisher instances or factories,
    or a "rather dynamic" number of children, by implementing `__getitem__`.

    The first case is usually used if the children are static, eg. the `RootPublisher`
    has fixed children (`ClientsPublisher`, `SchedulesPublisher`, ...), while the second
    case is best applied if the children are sourced from the database, since
    only one publisher, for the requested child, needs to be constructed.

    An example best illustrates this::

        class RootPublisher(Publisher):
            companion = 'dr'

            def children(self):
                return {
                    'clients': ClientsPublisher(self.dr.clients),
                    'schedules': SchedulesPublisher(self.dr.schedules),
                    # ...
                }

    On the other hand, here is how `ClientsPublisher` handles it's children::

        class ClientsPublisher(Publisher):
            companion = 'clients'

            def __getitem__(self, hostname):
                client = self.clients[hostname]
                return ClientPublisher(client)

    Note that, since `ClientsPublisher` was provided by `RootPublisher` the companion
    of `ClientsPublisher` is `data_root().clients` -- so `__getitem__` here only
    loads the required client from the database.

    Also note how no extra error handling is required: *clients* is already a mapping
    itself, so if no client with *hostname* exists it will raise `KeyError`.

    This might seem a bit confusing and convoluted, however, it allows implicit
    URL generation and avoids having to define many URL patterns by hand. It also
    decouples components very efficiently, since URLs are both resolved and generated
    by the hierarchy, so plugins can just "hook into" the system and don't need to
    bother defining URLs that don't conflict with core URLs.

    .. rubric:: Additional views

    Additional views can be added by adding *something_view* methods and adding it to
    the `views` property::

        class MyPublisher(Publisher):
            views = ('edit', )

            def view(self, request):
                ...

            def edit_view(self, request):
                ...

    In the URL hierarchy these are addressed through the ``view`` query parameter, eg.
    */clients/foo/?view=edit*. The query parameter converts dashes to underscores, eg.
    *?view=latest_job* and *?view=latest-job* are identical.
    """
    companion = 'companion'
    views = ()

    def __init__(self, companion):
        setattr(self, type(self).companion, companion)
        self.parent = None
        self.segment = None

    @property
    def name(self):
        """
        Name of the publisher for hookspec purposes. Defaults to *class.companion*.
        """
        return type(self).companion

    def get_companion(self):
        """Returns the companion object."""
        return getattr(self, type(self).companion)

    ###################
    # Children
    ###################

    def get(self, segment):
        """
        Return child from *segment* or raise KeyError.

        First tries subscription (`__getitem__`), then looks up in `children`.
        Ensures that *child.segment* and *child.parent* are set correctly.
        """
        try:
            child = self[segment]
        except KeyError:
            child = self.children()[segment]
        child.segment = segment
        child.parent = self
        return child

    def children(self):
        """
        Return a mapping of child names to child publishers.

        Make sure to call into `children_hook`, like so::

            def children(self):
                return self.children_hook({
                    ...
                })
        """
        return self.children_hook({})

    def children_hook(self, children):
        """
        Post-process result of `children`.

        This adds plugin children via `borgcube_web_children` and ensures that all
        children know their parent and segment.
        """
        list_of_children = hook.borgcube_web_children(publisher=self, children=children)
        for c in list_of_children:
            for k, v in c.items():
                if k in children:
                    log.warning('%s: duplicate child %s (%s)', self, k, v)
                    continue
            children.update(c)
        for k, v in children.items():
            v.segment = k
            v.parent = self
        return children

    def __getitem__(self, item):
        """
        Return published child object or raise KeyError

        Defaults to always raising `KeyError`.
        """
        raise KeyError

    ###################
    # Traversal
    ###################

    def redirect_to(self, view=None, permanent=False):
        """Return a HTTP redirect response to this publisher and *view*."""
        return redirect(self.reverse(view), permanent=permanent)

    def reverse(self, view=None):
        """Return the path to this publisher and *view*."""
        assert self.parent, 'Cannot reverse Publisher without a parent'
        assert self.segment, 'Cannot reverse Publisher without segment'
        path = self.parent.reverse()
        assert path.endswith('/'), 'Incorrect Publisher.reverse result: did not end in a slash?'
        path += urlquote(self.segment) + '/'
        if view:
            view = view.replace('_', '-')
            path += '?view=' + view
        return path

    def resolve(self, path_segments, view=None):
        """
        Resolve reversed *path_segments* to a view or raise `Http404`.

        Note: *path_segments* is destroyed in the process.
        """

        try:
            segment = path_segments.pop()
            if not segment:
                return self.view
        except IndexError:
            # End of the path -> resolve view
            if view:
                # Canonicalize the view name, replacing HTTP-style dashes with underscores,
                # eg. /client/foo/?view=latest-job means the same as /client/foo/?view=latest_job
                view = view.replace('-', '_')

                try:
                    # Make sure that this is an intentionally accessible view, not some coincidentally named method.
                    self.views.index(view)
                except ValueError:
                    raise Http404

                # Append view_ namespace eg. latest_job_view
                view_name = view + '_view'
                return getattr(self, view_name)
            else:
                return self.view

        try:
            return self.get(segment).resolve(path_segments, view)
        except KeyError:
            raise Http404

    ###################
    # Views
    ###################

    def render(self, request, template=None, context={}):
        """
        Return a TemplateResponse for *request*, *template* and *context*.

        The final context is constructed as follows:

        1. Start with an empty dictionary
        2. Add *publisher* (=self), the correctly named companion (=self.companion), *base_template*
           and a None *secondary_menu*.
        3. Add what `self.context` returns
        4. Add *context*.

        If *template* is None, then the `base_template` is used.
        """
        base_template = self.base_template(request)
        base_context = {
            'publisher': self,
            type(self).companion: self.get_companion(),
            'base_template': base_template,
            'secondary_menu': None,
        }
        base_context.update(self.context(request))
        base_context.update(context)
        return TemplateResponse(request, template or base_template, base_context)

    def base_template(self, request):
        return 'base.html'

    def context(self, request):
        """
        Return the "base context" for *request*.
        """
        return {}

    def view(self, request):
        """
        The default view of this object.

        This implementation raises `Http404`.
        """
        raise Http404


class ExtensiblePublisher(Publisher, PublisherMenu):
    """
    An extensible publisher implements publishers which are extended by `ExtendingPublisher` s.

    This allows to decouple the publishing of child objects from the publisher of an object,
    by allowing other parts and plugins to hook into the display and present their content
    wrapped up in your visual framework.

    An extensible publisher always has a menu entry that is used for secondary navigation
    between the ExtensiblePublisher and a number of ExtendingPublishers, which appear
    at the same level (although the are technically subordinate).

    The extending publishers are attached in the regular way through `children_hook`.
    """
    menu_text = ''

    def render(self, request, template=None, context=None):
        """
        Return a TemplateResponse for *request*, *template* and *context*.

        The final context is constructed as follows:

        1. Start with an empty dictionary
        2. Add *publisher* (=self), and the correctly named companion (=self.companion)
        3. Add what `self.context` returns
        4. Add *context*.

        *template* refers to a content template that dynamically extends the
        *base_template* passed in the template context.
        """
        context = context or {}
        context.setdefault('secondary_menu', self._construct_menu(request))
        return super().render(request, template, context)

    def base_template(self, request):
        return 'extensible.html'

    def _construct_menu(self, request):
        def item(publisher):
            return {
                'url': publisher.reverse(),
                'text': publisher.menu_text,
                'items': []
            }

        menu = [item(self)]
        for child in self.children().values():
            if not getattr(child, 'menu_descend', False):
                continue
            menu.append(item(child))
        return menu


class ExtendingPublisher(Publisher, PublisherMenu):
    def render(self, request, template=None, context=None):
        return self.parent.render(request, template, context)
