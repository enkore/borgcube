import datetime
import logging
import signal
from functools import partial

from django.utils.module_loading import import_string
from django.utils.timezone import now

from borgcube.core.models import ScheduleItem

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
    for si in ScheduleItem.objects.all():
        occurence = si.recurrence.after(this_very_moment, dtstart=si.recurrence_start)
        if latest_executions.get(si.pk) == occurence:
            continue
        if occurence and abs((occurence - this_very_moment).total_seconds()) < 10:
            latest_executions[si.pk] = occurence
            execute(apiserver, si)


def execute(apiserver, schedule_item):
    log.debug('Executing si %s', schedule_item)
    callable = import_string(schedule_item.py_class)
    callable(apiserver, schedule_item.py_args)



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
