import logging

from borg.helpers import Manifest
from django.utils.translation import ugettext_lazy as _
from django import forms

import transaction

from borg.archive import ArchiveChecker

from borgcube.core.models import Job, JobExecutor, Evolvable, s
from borgcube.utils import tee_job_logs, open_repository

log = logging.getLogger(__name__)


class CheckConfig(Evolvable):
    def __init__(self, repository,
                 label, check_repository, verify_data, check_archives, check_only_new_archives):
        self.repository = repository
        self.label = label
        self.check_repository = check_repository
        self.verify_data = verify_data
        self.check_archives = check_archives
        self.check_only_new_archives = check_only_new_archives

    def create_job(self):
        job = CheckJob(self)
        transaction.get().note(
            'Created check job from check config %s on repository %s' % (self.oid, self.repository.oid))
        log.info('Created job for check config %s (repository is %s / %s)',
                 self.oid, job.repository.name, job.repository.url)
        return job

    class Form(forms.Form):
        label = forms.CharField()

        check_repository = forms.BooleanField(initial=True, required=False)
        verify_data = forms.BooleanField(initial=False, required=False,
                                         help_text=_('Verify all data cryptographically (slow)'))
        check_archives = forms.BooleanField(initial=True, required=False)

        check_only_new_archives = forms.BooleanField(
            initial=False, required=False,
            help_text=_('Check only archives added since the last check'))


class CheckJobExecutor(JobExecutor):
    name = 'check-job'

    @classmethod
    def prefork(cls, job):
        job.update_state(CheckJob.State.job_created, CheckJob.State.repository_check)

    @classmethod
    def run(cls, job):
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
            if self.config.check_repository:
                self.check_repository(repository)
            if self.config.verify_data or self.config.check_archives:
                self.job.update_state(CheckJob.State.repository_check, CheckJob.State.verify_data)
                archive_checker = self.get_archive_checker(repository)
                if self.config.verify_data:
                    self.verify_data(repository, archive_checker)
                self.job.update_state(CheckJob.State.verify_data, CheckJob.State.archives_check)
                if self.config.check_archives:
                    self.check_archives(repository, archive_checker)
            else:
                self.job.update_state(CheckJob.State.verify_data, CheckJob.State.archives_check)
        self.job.update_state(CheckJob.State.archives_check, CheckJob.State.done)

    def get_archive_checker(self, repository):
        log.debug('Initialising archive checker')
        check = ArchiveChecker()
        check.repository = repository
        check.repair = False
        check.check_all = True
        check.init_chunks()
        log.debug('Initialised repository chunks')
        check.key = check.identify_key(repository)
        log.debug('Identified key: %s', type(check.key).__name__)
        return check

    def check_repository(self, repository):
        log.debug('Beginning repository check')
        if not repository.check():
            log.error('Repository check reported|repaired errors in %s (%r)', self.repository.name,
                      self.repository.url)
            self.job.force_state(CheckJob.State.failed)
            return
        log.debug('Repository check complete (success)')

    def verify_data(self, repository, archive_checker):
        archive_checker.verify_data()

    def check_archives(self, repository, check):
        if Manifest.MANIFEST_ID not in check.chunks:
            log.error('Repository manifest not found!')
            check.manifest = check.rebuild_manifest()
        else:
            check.manifest, _ = Manifest.load(repository, key=check.key)
        check.rebuild_refcounts(sort_by='ts')
        check.orphan_chunks_check()
        check.finish()


class CheckJob(Job):
    short_name = 'check'
    verbose_name = _('Check data')
    executor = CheckJobExecutor

    class State(Job.State):
        repository_check = s('repository_check', _('Checking repository'))
        verify_data = s('verify_data', _('Verifying data'))
        archives_check = s('archives_check', _('Checking archives'))

    def __init__(self, config: CheckConfig):
        super().__init__(config.repository)
        self.config = config
