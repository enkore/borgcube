from borgcube.vendor import pluggy

hookspec = pluggy.HookspecMarker('borgcube')


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
