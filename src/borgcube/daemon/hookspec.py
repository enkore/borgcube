import logging

from borgcube.vendor import pluggy
from borgcube.core.models import Job
from borgcube.utils import hook

log = logging.getLogger('borgcubed')
hookspec = pluggy.HookspecMarker('borgcube')


@hookspec
def borgcubed_startup(apiserver):
    """
    Called after borgcubed has fully started up.

    *apiserver* is the daemon.APIServer instance handling this. Interesting APIs are:

    def error(self, message, *parameters):
        Log error *message* formatted (%) with *parameters*. Return response dictionary.

    def queue_job(self, job):
        Enqueue *job* instance for execution.
    """


@hookspec(firstresult=True)
def borgcubed_handle_request(apiserver, request):
    """
    Handle *request* and return a response dictionary.

    request['command'] is the command string. If this is not for you, return None.
    """


@hookspec
def borgcubed_idle(apiserver):
    """
    Called on every 'idle' iteration in the daemon. This typically occurs roughly every second.
    """


@hookspec(firstresult=True)
def borgcubed_job_executor(job_id):
    """
    Return JobExecutor class for *job_id* (str) or None.
    """


@hookspec
def borgcubed_job_exit(apiserver, job_id, exit_code, signo):
    """
    Called when a job child process is reaped.

    *job_id* specifies the job, while *exit_code* is the exit code of the process.
    *signo* is the POSIX signal number. If the process did not exit due to a signal,
    *signo* is zero.
    """


@hookspec(firstresult=True)
def borgcubed_client_call(apiclient, call):
    """
    Called if an unknown APIClient method *call* (str) is invoked.

    Return a client function that should handle the call.

    Return None if you don't care about it.

    You are likely interested in this *apiclient* API::

    def do_request(self, request_dict):
        Send *request_dict* to the borgcube daemon and return the response dictionary.

    Don't forget to raise the appropiate APIError if the daemon returns an error.
    """


class JobExecutor:
    name = 'job-executor'

    @classmethod
    def can_run(cls, job_id):
        job = Job.objects.get(id=job_id)
        blocking_jobs = list(Job.objects.filter(repository=job.repository).exclude(state__in=Job.State.STABLE))
        hook.borgcube_job_blocked(job=job, blocking_jobs=blocking_jobs)
        if blocking_jobs:
            log.debug('Job %s blocked by running backup jobs: %s',
                      job.id, ' '.join('{} ({})'.format(job.id, job.state) for job in blocking_jobs))
        return not blocking_jobs

    @classmethod
    def prefork(cls, job_id):
        pass

    @classmethod
    def run(cls, job_id):
        raise NotImplementedError
