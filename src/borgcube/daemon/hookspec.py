from borgcube.vendor import pluggy
from borgcube.core.models import Job
from borgcube.utils import hook

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


class JobExecutor:
    name = 'job-executor'

    @classmethod
    def can_run(cls, job_id):
        job = Job.objects.get(id=job_id)
        return not hook.borgcube_job_blocked(job=job)

    @classmethod
    def prefork(cls, job_id):
        pass

    @classmethod
    def run(cls, job_id):
        raise NotImplementedError
