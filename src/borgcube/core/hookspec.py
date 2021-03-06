
from borgcube.vendor import pluggy


hookspec = pluggy.HookspecMarker('borgcube')


@hookspec
def borgcube_startup(process):
    """
    Called after application is configured and all plugins were discovered.

    *process* identifies the process and may be None. Otherwise it can be one of:

    - "borgcubed"
    - "proxy"
    - "manage" (this may include running the web frontend)
    """


@hookspec
def borgcube_job_blocked(job, blocking_jobs):
    """
    Called to sort out whether *job* is blocked by any *blocking_jobs*.

    *blocking_jobs* is a list of jobs that are aimed at the same repository as *job* and whose state
    is not in Job.State.STABLE.

    Remove any false positives from *blocking_jobs* that might be there because of special snowflake semantics
    with your jobs.

    If any *blocking_jobs* remain, *job* is considered blocked.
    """


@hookspec
def borgcube_job_pre_state_update(job, current_state, target_state):
    """
    Called before the state of *job* is updated from *current_state* (BackupJob.State) to *target_state* (ditto).
    """


@hookspec
def borgcube_job_post_state_update(job, prior_state, current_state):
    """
    Called after the state of *job* was updated from *prior_state* (BackupJob.State) to *current_state*.

    *job* is already saved, but the database transaction has not yet completed.
    """


@hookspec
def borgcube_job_post_force_state(job, forced_state):
    """
    Called after the state of *job* was forced to *forced_state* (BackupJob.State).
    """


@hookspec
def borgcube_job_failure_cause(job, kind, kwargs):
    """
    Called after the failure cause (defined by *kind* (str) and it's *kwargs*) is set for *job*.
    """


@hookspec
def borgcube_job_created(job):
    """
    Called when a *job* was created, but before it will be executed.
    """


@hookspec
def borgcube_job_pre_delete(job):
    """
    Called before *job* will be deleted.
    """


@hookspec
def borgcube_archive_added(archive):
    """
    Called after *archive* was added (core.models.Archive).
    """


@hookspec
def borgcube_archive_pre_delete(archive):
    """
    Called before *archive* (core.models.Archive) will be deleted.
    """