import logging

from borg.helpers import Manifest
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import ugettext_lazy as _
from django import forms

import transaction

from borg.archive import ArchiveChecker

from borgcube.core.models import Job, Evolvable, s
from borgcube.utils import tee_job_logs, open_repository, data_root
from .hookspec import JobExecutor
from .client import APIError

log = logging.getLogger('borgcubed.checkjob')


def borgcubed_job_executor(job):
    if job.short_name == 'check':
        return CheckJobExecutor


def borgcubed_handle_request(apiserver, request):
    if request['command'] != 'initiate-check-job':
        return
    try:
        check_config_id = request['check_config']
    except KeyError as ke:
        return apiserver.error('Missing parameter %r', ke.args[0])
    try:
        check_config = CheckConfig.objects.get(id=check_config_id)
    except ObjectDoesNotExist:
        return apiserver.error('No such JobConfig')
    job = CheckJob.from_config(check_config)
    job.save()
    log.info('Created job %s for check config %d (repository is %s / %s)',
             job.id, check_config.id, job.repository.name, job.repository.url)
    apiserver.queue_job(job)
    return {
        'success': True,
        'job': str(job.id),
    }


def borgcubed_client_call(apiclient, call):
    if call != 'initiate_check_job':
        return

    def initiate_check_job(check_config):
        reply = apiclient.do_request({
            'command': 'initiate-check-job',
            'check_config': check_config.oid,
        })
        if not reply['success']:
            log.error('APIClient.initiate_check_job(%s) failed: %s', check_config.oid, reply['message'])
            raise APIError(reply['message'])
        log.info('Initiated check job %s', reply['job'])
        transaction.begin()
        return data_root()._p_jar[bytes.fromhex(reply['job'])]
    return initiate_check_job


class CheckConfig(Evolvable):
    def __init__(self, label, repository, check_repository, verify_data, check_archives, check_only_new_archives):
        self.label = label
        self.repository = repository
        self.check_repository = check_repository
        self.verify_data = verify_data
        self.check_archives = check_archives
        self.check_only_new_archives = check_only_new_archives

    class Form(forms.Form):
        label = forms.CharField()
        repository = None  # TODO

        check_repository = forms.BooleanField(initial=True, required=False)
        verify_data = forms.BooleanField(initial=False, required=False,
                                         help_text=_('Verify all data cryptographically (slow)'))
        check_archives = forms.BooleanField(initial=True, required=False)

        check_only_new_archives = forms.BooleanField(
            initial=False, required=False,
            help_text=_('Check only archives added since the last check'))


class CheckJob(Job):
    short_name = 'check'

    class State(Job.State):
        repository_check = s('repository_check', _('Checking repository'))
        verify_data = s('verify_data', _('Verifying data'))
        archives_check = s('archives_check', _('Checking archives'))

    def __init__(self, repository, config):
        super().__init__(repository)
        self.config = config


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

