import logging

from django.core.exceptions import ObjectDoesNotExist

from borg.archive import ArchiveChecker

from borgcube.core.models import CheckJob
from borgcube.utils import tee_job_logs, open_repository
from .hookspec import JobExecutor

log = logging.getLogger('borgcubed.checkjob')


def borgcubed_job_executor(job_id):
    if CheckJob.objects.filter(id=job_id).exists():
        return CheckJobExecutor


def borgcubed_job_exit(apiserver, job_id, exit_code, signo):
    try:
        job = CheckJob.objects.get(id=job_id)
    except ObjectDoesNotExist:
        return
    if exit_code or signo:
        job.force_state(CheckJob.State.failed)


class CheckJobExecutor(JobExecutor):
    name = 'check-job'

    @classmethod
    def prefork(cls, job_id):
        job = CheckJob.objects.get(id=job_id)
        initial_state = CheckJob.State.repository_check
        if not job.config.repository_check:
            initial_state = CheckJob.State.verify_data
        if not job.config.verify_data:
            initial_state = CheckJob.State.archives_check
        job.update_state(CheckJob.State.job_created, initial_state)

    @classmethod
    def run(cls, job_id):
        job = CheckJob.objects.get(id=job_id)
        executor = cls(job)
        executor.execute()

    def __init__(self, job):
        tee_job_logs(job)
        self.job = job
        self.config = job.config
        self.repository = job.repository

    def execute(self):
        log.debug('Beginning check job on repository %r', self.repository.url)
        with open_repository(self.repository) as repository:
            if self.config.repository_check:
                log.debug('Beginning repository check')
                if not repository.check():
                    log.error('Repository check reported|repaired errors in %s (%r)', self.repository.name, self.repository.url)
                    self.job.force_state(CheckJob.State.failed)
                    return
                log.debug('Repository check complete (success)')
                self.job.update_state(CheckJob.State.repository_check, CheckJob.State.verify_data)
            archive_checker = ArchiveChecker


from borg.repository import Repository