import json
import logging

import transaction

from dateutil.relativedelta import relativedelta

from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.utils.timezone import localtime, now
from django.utils.translation import ugettext_lazy as _

from borgcube.core.models import Schedule, ScheduledAction
from borgcube.utils import data_root, find_oid
from . import Publisher, ExtensiblePublisher

log = logging.getLogger(__name__)


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
        schedule = find_oid(self.schedules, oid)
        return SchedulePublisher(schedule)

    def view(self, request):
        try:
            month = localtime(now()).replace(year=int(request.GET['year']), month=int(request.GET['month']), day=1)
        except (KeyError, TypeError):
            month = localtime(now())
        sheet = CalendarSheet(month)
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


class SchedulePublisher(ExtensiblePublisher, ScheduledActionFormMixin):
    companion = 'schedule'
    views = ('delete', 'action_form', )
    menu_text = _('Schedule')

    def context(self, request):
        context = super().context(request)
        context['title'] = _('Edit schedule {}').format(self.schedule.name)
        return context

    def default_template(self, request):
        return 'core/schedule/add.html'

    def view(self, request):
        data = request.POST or None
        return schedule_add_and_edit(self.render, request, data, self.schedule, context={
            'submit': _('Save changes'),
            'schedule': self.schedule,
        })

    def delete_view(self, request):
        if request.method == 'POST':
            data_root().schedules.remove(self.schedule)
            transaction.get().note('Deleted schedule %s' % self.schedule.oid)
            transaction.commit()
        return self.parent.redirect_to()
