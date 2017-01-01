import datetime
import logging
import signal
from functools import partial

from django.utils.module_loading import import_string
from django.utils.timezone import now

from borgcube.core.models import Schedule, ScheduledAction
from borgcube.utils import data_root

log = logging.getLogger('borgcubed.scheduler')

latest_executions = {}


# def borgcubed_startup(apiserver):
#    signal.signal(signal.SIGALRM, partial(schedule_sweep, apiserver))


def borgcubed_idle(apiserver):
    """Check schedule. Are we supposed to do something right about now?"""
#    seconds = seconds_until_next_occurence()
#    log.debug('setting alarm clock to beep in %d seconds', seconds)
#    signal.alarm(seconds)
    this_very_moment = now()
    for schedule in data_root().schedules:
        # TODO: when django-recurrence#81 is resolved, use cache.
        occurence = schedule.recurrence.after(this_very_moment, dtstart=schedule.recurrence_start)
        if latest_executions.get(schedule._p_oid) == occurence:
            continue
        if occurence and abs((occurence - this_very_moment).total_seconds()) < 10:
            latest_executions[schedule._p_oid] = occurence
            execute(apiserver, schedule)


def execute(apiserver, schedule):
    log.debug('Executing schedule %s', schedule)
    for action in schedule.actions:
        action.execute(apiserver)


def seconds_until_next_occurence():
    this_very_moment = now()
    next_sweep = this_very_moment + datetime.timedelta(days=10)
    for si in ScheduleItem.objects.all():
        occurence = si.recurrence.after(
            this_very_moment, dtstart=si.recurrence_start, dtend=next_sweep,
        )
        if occurence and occurence < next_sweep:
            next_sweep = occurence
    delta_secs_into_the_future = int(max((next_sweep - now()).total_seconds(), 0))
    return delta_secs_into_the_future
