import logging

from borgcube.vendor import pluggy

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


@hookspec
def borgcubed_job_exit(apiserver, job, exit_code, signo):
    """
    Called when a job child process is reaped.

    *job* is the job, while *exit_code* is the exit code of the process.
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
