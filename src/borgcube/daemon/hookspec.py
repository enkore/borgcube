from borgcube.vendor import pluggy

hookspec = pluggy.HookspecMarker('borgcube')


@hookspec(firstresult=True)
def borgcubed_handle_request(apiserver, request):
    """
    Handle *request* and return a response dictionary.

    request['command'] is the command string. If this is not for you, return None.

    *apiserver* is the daemon.APIServer instance handling this. Interesting APIs are:

    def error(self, message, *parameters):
        Log error *message* formatted (%) with *parameters*. Return response dictionary.

    def queue_job(self, job):
        Enqueue *job* instance for execution.
    """


@hookspec(firstresult=True)
def borgcubed_job_executor(job_id):
    """
    Return JobExecutor class for *job_id* (str) or None.
    """


class JobExecutor:
    name = 'job-executor'

    @classmethod
    def can_run(cls, job_id):
        return True

    @classmethod
    def prefork(cls, job_id):
        pass

    @classmethod
    def run(cls, job_id):
        raise NotImplementedError
