import logging
import itertools
import json

from urllib.parse import quote as urlquote, unquote as urlunquote

from django import forms
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, get_object_or_404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.timezone import now, localtime
from django.utils.translation import ugettext_lazy as _

import transaction

from borgcube.core.models import Client, Repository, RshClientConnection
from borgcube.core.models import Job
from borgcube.core.models import Schedule, ScheduledAction
from borgcube.daemon.client import APIClient
from borgcube.utils import data_root, find_oid_or_404, hook

from borgcube.job.backup import BackupConfig
from borgcube.job.check import CheckConfig

from ..metrics import WebData

log = logging.getLogger(__name__)


def paginate(request, things, num_per_page=40, prefix=''):
    if prefix:
        prefix += '_'
    paginator = Paginator(things, num_per_page)
    page = request.GET.get(prefix + 'page')
    try:
        return paginator.page(page)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


def job_view(request, job_id):
    job = get_object_or_404(Job, id=job_id)


def job_cancel(request, job_id):
    job = data_root().jobs[int(job_id)]
    daemon = APIClient()
    daemon.cancel_job(job)
    return redirect(client_view, job.client.hostname)


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


from functools import partial


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
                    'clients': ClientsPublisher.factory(self.dr.clients, self),
                    'schedules': SchedulesPublisher.factory(self.dr.schedules, self),
                    # ...
                }

    Note how `Publisher.factory` directly provides a factory.

    On the other hand, here is how `ClientsPublisher` handles it's children::

        class ClientsPublisher(Publisher):
            companion = 'clients'

            def __getitem__(self, hostname):
                client = self.clients[hostname]
                return ClientPublisher(client, self)

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

    @classmethod
    def factory(cls, companion, parent=None):
        return partial(cls, companion, parent)

    def __init__(self, companion, parent=None, segment=None):
        setattr(self, type(self).companion, companion)
        self.parent = parent
        self.segment = segment

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

    def children(self):
        """
        Return a mapping of child names to child publishers or factories.

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

        Call `children` and index return value with *item* by default.
        """
        v = self.children()[item]
        try:
            return v()
        except TypeError:
            return v

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

        def out_of_hierarchy(segment):
            child = hook.borgcube_web_resolve(publisher=self, segment=segment)
            if child:
                # A plugin publisher is mounted here, resolve further.
                child.parent = self
                child.segment = segment
                return child.resolve(path_segments, view)
            else:
                # No matches at all -> 404.
                raise Http404

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
            child = self[segment]
            child.parent = self
            child.segment = segment
            return child.resolve(path_segments, view)
        except KeyError:
            return out_of_hierarchy(segment)

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

    def render(self, request, template, context=None):
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


class RootPublisher(Publisher):
    companion = 'dr'
    views = ()

    def children(self):
        return self.children_hook({
            'clients': ClientsPublisher.factory(self.dr.clients, self),
            'schedules': SchedulesPublisher.factory(self.dr.schedules, self),
            'repositories': RepositoriesPublisher.factory(self.dr.repositories, self),
            'management': ManagementAreaPublisher.factory(self.dr.ext, self),
        })

    def view(self, request):
        recent_jobs = itertools.islice(reversed(self.dr.jobs), 20)
        return self.render(request, 'core/dashboard.html', {
            'metrics': self.dr.plugin_data(WebData).metrics,
            'recent_jobs': recent_jobs,
        })

    def reverse(self, view=None):
        return '/'


class ClientsPublisher(Publisher):
    companion = 'clients'
    views = ('add',)

    def __getitem__(self, hostname):
        client = self.clients[hostname]
        return ClientPublisher(client, self)

    def view(self, request):
        return TemplateResponse(request, 'core/client/list.html', {
            'm': Client,
            'clients': self.clients.values(),
        })

    def add_view(self, request):
        data = request.POST or None
        client_form = Client.Form(data)
        connection_form = RshClientConnection.Form(data)
        if data and client_form.is_valid() and connection_form.is_valid():
            connection = RshClientConnection(**connection_form.cleaned_data)
            client = Client(connection=connection, **client_form.cleaned_data)
            transaction.get().note('Added client %s' % client.hostname)
            transaction.commit()
            return self.redirect_to()
        return self.render(request, 'core/client/add.html', {
            'client_form': client_form,
            'connection_form': connection_form,
        })


class ClientPublisher(Publisher):
    companion = 'client'
    views = ('edit', )

    def children(self):
        return self.children_hook({
            'job-configs': JobConfigsPublisher(self.client.job_configs),
        })

    def view(self, request):
        jobs = paginate(request, self.client.jobs.values(), prefix='jobs')
        return self.render(request, 'core/client/view.html', {
            'client': self.client,
            'jobs': jobs,
        })

    def edit_view(self, request):
        client = self.client
        data = request.POST or None
        client.connection._p_activate()
        client_form = Client.Form(data, initial=client.__dict__)
        del client_form.fields['hostname']
        connection_form = RshClientConnection.Form(data, initial=client.connection.__dict__)
        if data and client_form.is_valid() and connection_form.is_valid():
            client._update(client_form.cleaned_data)
            client.connection._update(connection_form.cleaned_data)
            transaction.get().note('Edited client %s' % client.hostname)
            transaction.commit()
            return self.redirect_to()
        return self.render(request, 'core/client/edit.html', {
            'client': client,
            'client_form': client_form,
            'connection_form': connection_form,
        })


class JobConfigForm(forms.Form):
    COMPRESSION_CHOICES = [
        ('none', _('No compression')),
        ('lz4', _('LZ4 (fast)')),
    ] \
        + [('zlib,%d' % level, _('zlib level %d') % level) for level in range(1, 10)] \
        + [('lzma,%d' % level, _('LZMA level %d') % level) for level in range(1, 7)]

    label = forms.CharField()

    repository = Repository.ChoiceField()

    one_file_system = forms.BooleanField(initial=True, required=False,
                                         help_text=_('Don\'t cross over file system boundaries.'))

    compression = forms.ChoiceField(initial='lz4', choices=COMPRESSION_CHOICES,
                                    help_text=_('Compression is performed on the client, not on the server.'))

    paths = forms.CharField(widget=forms.Textarea,
                            help_text=_('Paths to include in the backup, one per line. At least one path is required.'))

    # TODO explain format
    excludes = forms.CharField(widget=forms.Textarea, required=False,
                               help_text=_('Patterns to exclude from the backup, one per line.'))

    class AdvancedForm(forms.Form):
        prefix = 'advanced'

        # TODO DurationField instead?
        checkpoint_interval = forms.IntegerField(min_value=0, initial=1800)

        read_special = forms.BooleanField(initial=False, required=False,
                                          help_text=_('Open and read block and char device files as well as FIFOs as if '
                                                      'they were regular files. Also follow symlinks pointing to these '
                                                      'kinds of files.'))
        ignore_inode = forms.BooleanField(initial=False, required=False,
                                          help_text=_('Ignore inode data in the file metadata cache used to detect '
                                                      'unchanged file.'))
        extra_options = forms.CharField(required=False,
                                        help_text=_('These options are passed verbatim to Borg on the client. Please '
                                                    'don\'t specify any logging options or --remote-path.'))


class JobConfigsPublisher(Publisher):
    companion = 'configs'
    views = ('add', )

    def __getitem__(self, oid):
        return JobConfigPublisher(find_oid_or_404(self.configs, oid))

    def add_view(self, request):
        client = self.parent.client
        data = request.POST or None
        form = JobConfigForm(data=data)
        advanced_form = JobConfigForm.AdvancedForm(data=data)
        if data and form.is_valid() and advanced_form.is_valid():
            config = form.cleaned_data
            config.update(advanced_form.cleaned_data)
            config['paths'] = config.get('paths', '').split('\n')
            config['excludes'] = [s for s in config.get('excludes', '').split('\n') if s]

            repository = config.pop('repository')
            job_config = BackupConfig(client=client, repository=repository, label=config['label'])
            job_config._update(config)
            client.job_configs.append(job_config)

            transaction.get().note('Added job config to client %s' % client.hostname)
            transaction.commit()

            # TODO StringListValidator
            # TODO Pattern validation
            # TODO fancy pattern editor with test area

            return self[job_config.oid].redirect_to()
        return self.render(request, 'core/client/config_add.html', {
            'form': form,
            'advanced_form': advanced_form,
        })


class JobConfigPublisher(Publisher):
    companion = 'config'
    views = ('delete', 'trigger', )

    def reverse(self, view=None):
        if view:
            return super().reverse(view)
        else:
            return self.parent.parent.reverse() + '#job-config-' + self.config.oid

    def view(self, request):
        client = self.config.client
        job_config = self.config
        data = request.POST or None
        job_config._p_activate()
        initial_data = dict(job_config.__dict__)
        initial_data['paths'] = '\n'.join(initial_data['paths'])
        initial_data['excludes'] = '\n'.join(initial_data['excludes'])
        form = JobConfigForm(data=data, initial=initial_data)
        advanced_form = JobConfigForm.AdvancedForm(data=data, initial=initial_data)
        if data and form.is_valid() and advanced_form.is_valid():
            config = form.cleaned_data
            config.update(advanced_form.cleaned_data)
            config['paths'] = config.get('paths', '').split('\n')
            config['excludes'] = [s for s in config.get('excludes', '').split('\n') if s]
            job_config._update(config)
            # TODO StringListValidator
            # TODO Pattern validation
            # TODO fancy pattern editor with test area

            transaction.get().note('Edited job config %s of client %s' % (job_config.oid, client.hostname))
            transaction.commit()

            return self.redirect_to()
        return self.render(request, 'core/client/config_edit.html', {
            'client': client,
            'form': form,
            'advanced_form': advanced_form,
            'job_config': job_config,
        })

    def delete_view(self, request):
        client = self.parent.parent.client
        if request.method == 'POST':
            client.job_configs.remove(self.config)
            # Could just leave it there, but likely not the intention behind clicking (delete).
            for schedule in data_root().schedules:
                for action in list(schedule.actions):
                    if getattr(action, 'job_config', None) == self.config:
                        schedule.actions.remove(action)
            transaction.get().note('Deleted job config %s from client %s' % (self.config.oid, client.hostname))
            transaction.commit()
        return self.redirect_to()

    def trigger_view(self, request):
        if request.method == 'POST':
            job = self.config.create_job()
            transaction.commit()
        return self.redirect_to()


def schedule_add_and_edit(render, request, data, schedule=None, context=None):
    if schedule:
        schedule._p_activate()
        form = Schedule.Form(data, initial=schedule.__dict__)
    else:
        form = Schedule.Form(data)
    action_forms = []

    # This generally works since pluggy loads plugin modules for us.
    classes = ScheduledAction.__subclasses__()
    log.debug('Discovered schedulable actions: %s', ', '.join(cls.dotted_path() for cls in classes))

    if schedule:
        for scheduled_action in schedule.actions:
            scheduled_action._p_activate()
            action_form = scheduled_action.form(initial=scheduled_action.__dict__)
            action_forms.append(action_form)

    if data:
        try:
            actions_data = json.loads(data['actions-data'])
        except KeyError:
            return HttpResponseBadRequest('Invalid POST data for schedule form. Is JavaScript disabled?')
        all_valid = form.is_valid()
        txn = transaction.get()

        if all_valid:
            if schedule:
                schedule.actions.clear()
                schedule._update(form.cleaned_data)
                txn.note('Edited schedule %s' % schedule.oid)
            else:
                schedule = Schedule(**form.cleaned_data)
                data_root().schedules.append(schedule)
                txn.note('Added schedule %s' % schedule.name)

        for serialized_action in actions_data:
            dotted_path = serialized_action.pop('class')
            action = ScheduledAction.get_class(dotted_path)
            if not action:
                log.error('invalid/unknown schedulable action %r, ignoring', dotted_path)
                continue
            action_form = action.form(serialized_action)

            valid = action_form.is_valid()
            all_valid &= valid
            if all_valid:
                scheduled_action = action(schedule, **action_form.cleaned_data)
                schedule.actions.append(scheduled_action)
                txn.note(' - Added scheduled action %s' % scheduled_action.dotted_path())
            action_forms.append(action_form)

        if all_valid:
            txn.commit()
            return request.publisher.redirect_to()
    context = dict(context or {})
    context.update({
        'form': form,
        'classes': {cls.dotted_path(): cls.name for cls in classes},
        'action_forms': action_forms,
    })
    return render(request, 'core/schedule/add.html', context)


from dateutil.relativedelta import relativedelta


class ScheduledActionFormMixin:
    def action_form_view(self, request):
        dotted_path = request.GET.get('class')
        cls = ScheduledAction.get_class(dotted_path)
        if not cls:
            log.error('scheduled_action_form request for %r which is not a schedulable action', dotted_path)
            return HttpResponseBadRequest()
        return HttpResponse(cls.Form().as_table())


class SchedulesPublisher(Publisher, ScheduledActionFormMixin):
    companion = 'schedules'
    views = ('list', 'add', 'action_form', )

    def __getitem__(self, oid):
        schedule = find_oid_or_404(self.schedules, oid)
        return SchedulePublisher(schedule, self)

    def view(self, request):
        try:
            month = localtime(now()).replace(year=int(request.GET['year']), month=int(request.GET['month']), day=1)
        except (KeyError, TypeError):
            month = localtime(now())
        sheet = self.CalendarSheet(month)
        schedules = self.schedules

        keep = request.GET.getlist('schedule')
        if keep:
            for i, schedule in reversed(list(enumerate(schedules))):
                if str(i) not in keep:
                    del schedules[i]

        schedules = [schedule for schedule in schedules if schedule.recurrence_enabled]

        colors = [
            '#e6e6e6',
            '#d4c5f9',
            '#fef2c0',
            '#f9d0c4',
        ]

        if len(schedules) > 1:
            for schedule in schedules:
                try:
                    schedule.color = colors.pop()
                except IndexError:
                    schedule.color = None

        for week in sheet.weeks:
            for day in week.days:
                day.schedules = []
                for schedule in schedules:
                    # Even with the cache there is still a scalability problem here in that rrule evaluation is
                    # strictly linear, so the further you go from DTSTART the more intermediary occurences are computed,
                    # so it'll only get slower (this is pretty much irrelevant for hourly and slower recurrence, so somewhat
                    # academic). It's *probably* possible to give an algorithm that calculates a new DTSTART for infinite
                    # recurrences that doesn't otherwise change the recurrence series, but I can't even begin to formulate
                    # one. However, there are certain trivial cases where such an algorithm would be trivial as well, so
                    # that'd be your solution right there.
                    occurences = schedule.recurrence.between(day.begin, day.end, cache=True, inc=True)
                    if occurences:
                        occurs = []
                        for occurence in occurences[:5]:
                            occurs.append(occurence.time().strftime('%X'))
                        if len(occurences) > 5:
                            occurs.append('…')
                        schedule.occurs = ', '.join(occurs)
                        day.schedules.append(schedule)

        return self.render(request, 'core/schedule/schedule.html', {
            'calsheet': sheet,
            'schedules': schedules,
            'prev_month': sheet.month - relativedelta(months=1),
            'next_month': sheet.month + relativedelta(months=1),
        })

    def list_view(self, request):
        return self.render(request, 'core/schedule/list.html', {
            'm': Schedule,
            'schedules': self.schedules,
        })

    def add_view(self, request):
        data = request.POST or None
        return schedule_add_and_edit(self.render, request, data, context={
            'title': _('Add schedule'),
            'submit': _('Add schedule'),
        })

    class CalendarSheet:
        # FYI I'm a masochist

        class Week:
            def __init__(self, first_day, days):
                self.first_day = first_day
                self.days = days
                self.number = first_day.datetime.isocalendar()[1]

        class Day:
            def __init__(self, datetime, off_month):
                self.begin = self.datetime = datetime
                self.end = datetime + relativedelta(days=1) - relativedelta(microseconds=1)
                self.date = datetime.date()
                self.off_month = off_month

        def __init__(self, datetime_month):
            self.month = datetime_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            self.month_end = self.month + relativedelta(months=1)

            weekday_delta = -self.month.weekday()
            self.sheet_begin = self.month + relativedelta(days=weekday_delta)

            weekday_delta = 7 - self.month_end.isoweekday()
            self.sheet_end = self.month_end
            if weekday_delta != 6:
                # Don't append a full week of the following month
                self.sheet_end += relativedelta(days=weekday_delta)

            self.weeks = []
            current = self.sheet_begin

            def day():
                off_month = current.month != self.month.month
                return self.Day(datetime=current, off_month=off_month)

            while current < self.sheet_end:
                week = self.Week(day(), [])
                self.weeks.append(week)
                for i in range(7):
                    week.days.append(day())
                    current += relativedelta(days=1)


class SchedulePublisher(ExtensiblePublisher, ScheduledActionFormMixin):
    companion = 'schedule'
    views = ('delete', 'action_form', )
    menu_text = _('Schedule')

    def view(self, request):
        data = request.POST or None
        return schedule_add_and_edit(self.render, request, data, self.schedule, context={
            'title': _('Edit schedule {}').format(self.schedule.name),
            'submit': _('Save changes'),
            'schedule': self.schedule,
        })

    def delete_view(self, request):
        if request.method == 'POST':
            data_root().schedules.remove(self.schedule)
            transaction.get().note('Deleted schedule %s' % self.schedule.oid)
            transaction.commit()
        return self.parent.redirect_to()


class RepositoriesPublisher(Publisher):
    companion = 'repositories'
    views = ('add', )

    def __getitem__(self, repository_id):
        repository = Repository.oid_get(repository_id)
        return RepositoryPublisher(repository, self)

    def view(self, request):
        return TemplateResponse(request, 'core/repository/list.html', {
            'm': Repository,
            'repositories': self.repositories,
        })

    def add_view(self, request):
        data = request.POST or None
        repository_form = Repository.Form(data)
        if data and repository_form.is_valid():
            repository = Repository(**repository_form.cleaned_data)
            data_root().repositories.append(repository)
            transaction.get().note('Added repository %s' % repository.name)
            transaction.commit()
            return self.redirect_to()
        return self.render(request, 'core/repository/add.html', {
            'repository_form': repository_form,
        })


class RepositoryPublisher(Publisher):
    companion = 'repository'
    views = ('edit', )

    def children(self):
        return self.children_hook({
            'check-configs': RepositoryCheckConfigsPublisher(self.repository, self),
        })

    def view(self, request):
        return self.render(request, 'core/repository/view.html', {
            'repository': self.repository,
        })

    def edit_view(self, request):
        data = request.POST or None
        repository = self.repository
        repository._p_activate()
        repository_form = Repository.Form(data, initial=repository.__dict__)
        if data and repository_form.is_valid():
            repository._update(repository_form.cleaned_data)
            transaction.get().note('Edited repository %s' % repository.oid)
            transaction.commit()
            return self.redirect_to()
        return self.render(request, 'core/repository/edit.html', {
            'repository': repository,
            'repository_form': repository_form,
        })


class RepositoryCheckConfigsPublisher(Publisher):
    companion = 'repository'
    views = ('add', )

    def __getitem__(self, config_id):
        print(config_id)
        config = find_oid_or_404(self.repository.job_configs, config_id)
        return RepositoryCheckConfigPublisher(config, self)

    def add_view(self, request):
        data = request.POST or None
        config_form = CheckConfig.Form(data)
        if data and config_form.is_valid():
            config = CheckConfig(self.repository, **config_form.cleaned_data)
            self.repository.job_configs.append(config)
            transaction.get().note('Added check config to repository %s' % self.repository.oid)
            transaction.commit()
            return self.parent.redirect_to()
        return self.render(request, 'core/repository/config_add.html', {
            'form': config_form,
        })


class RepositoryCheckConfigPublisher(Publisher):
    companion = 'config'
    views = ('edit', 'delete', 'trigger', )

    def edit_view(self, request):
        check_config = self.config
        data = request.POST or None
        check_config._p_activate()
        config_form = check_config.Form(data, initial=check_config.__dict__)
        if data and config_form.is_valid():
            check_config._update(config_form.cleaned_data)
            transaction.get().note('Edited check config %s on repository %s' % (check_config.oid, self.parent.repository.oid))
            transaction.commit()
            return self.parent.parent.redirect_to()
        return self.render(request, 'core/repository/config_edit.html', {
            'form': config_form,
        })

    def delete_view(self, request):
        if request.method == 'POST':
            repository = self.parent.repository
            repository.job_configs.remove(self.config)
            transaction.get().note('Deleted check config %s from repository %s' % (self.config.oid, repository.oid))
            transaction.commit()
        return self.parent.parent.redirect_to()

    def trigger_view(self, request):
        if request.method == 'POST':
            job = self.config.create_job()
            transaction.commit()
        return self.parent.parent.redirect_to()


class ManagementPublisher(Publisher, PublisherMenu):
    """
    Base class for management publishers (that want to be part of the management area).

    Inherits `PublisherMenu` to enable the menu entry, and uses *management.html* as a
    base_template, which enables the sidebar used for navigation in the management area.
    It also adds the *management* key to the template context which is used for signalling
    middleware.
    """
    def base_template(self, request):
        return 'management.html'

    def context(self, request):
        return {
            'management': True,
        }


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


def object_publisher(request, path):
    """
    Renders a *path* against the *RootPublisher*.

    The request will receive the following attributes:

    - *publisher*: the publisher handling the request
    - *view_name*: the verbatim view name (?view=...)
    """
    view_name = request.GET.get('view')
    path_segments = path.split('/')
    path_segments.reverse()

    root_publisher = RootPublisher(data_root())
    view = root_publisher.resolve(path_segments, view_name)

    try:
        request.publisher = view.__self__
        request.view_name = view_name
    except AttributeError:
        # We don't explicitly prohibit the resolver to return a view callable that isn't
        # part of a publisher.
        pass
    response = view(request)
    if response is None:
        qualname = view.__module__ + '.' + view.__qualname__
        raise ValueError('The view %s returned None instead of a HTTPResponse' % qualname)
    return response
