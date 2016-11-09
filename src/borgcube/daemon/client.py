
import logging

from django.conf import settings

import zmq

from ..core.models import Job

log = logging.getLogger(__name__)


class APIError(RuntimeError):
    pass


class APIClient:
    """
    Client to talk to the backend daemon (borgcubed)

    All of these can raise zmq.ZMQError, zmq.Again etc. and these should be handled gracefully (ie not with a 500).
    """

    def __init__(self, address=settings.DAEMON_ADDRESS, context=None):
        self.socket = (context or zmq.Context.instance()).socket(zmq.REQ)
        self.socket.rcvtimeo = 2000
        self.socket.sndtimeo = 2000
        self.socket.linger = 2000
        self.socket.connect(address)

    def initiate_job(self, client, job_config):
        self.socket.send_json({
            'command': 'initiate-job',
            'client': client.hostname,
            'job_config': job_config.id,
        })
        reply = self.socket.recv_json()
        if not reply['success']:
            log.error('APIClient.initiate_job(%r, %d) failed: %s', client.hostname, job_config.id, reply['message'])
            raise APIError(reply['message'])
        log.info('Initiated job %s', reply['job'])
        return Job.objects.get(id=reply['job'])

    def cancel_job(self, job):
        self.socket.send_json({
            'command': 'cancel-job',
            'job_id': str(job.id),
        })
        reply = self.socket.recv_json()
        if not reply['success']:
            log.error('APIClient.cancel_job(%r) failed: %s', job.id, reply['message'])
            raise APIError(reply['message'])
        log.info('Cancelled job %s', job.id)
