
import logging

from django.conf import settings

import zmq

from ..utils import hook
from .utils import get_socket_addr

log = logging.getLogger(__name__)


class APIError(RuntimeError):
    pass


class APIClient:
    """
    Client to talk to the backend daemon (borgcubed)

    All of these can raise zmq.ZMQError, zmq.Again etc. and these should be handled gracefully (ie not with a 500).
    """

    def __init__(self, address=None, context=None):
        address = address or ('ipc://' + get_socket_addr('daemon'))
        self.socket = (context or zmq.Context.instance()).socket(zmq.REQ)
        self.socket.rcvtimeo = 2000
        self.socket.sndtimeo = 2000
        self.socket.linger = 2000
        self.socket.connect(address)

    def __getattr__(self, item):
        handler = hook.borgcubed_client_call(apiclient=self, call=item)
        if not handler:
            raise AttributeError('No such API: %r' % item)
        return handler

    def do_request(self, request_dict):
        """
        Send *request_dict* to the borgcube daemon and return the response dictionary.
        """
        self.socket.send_json(request_dict)
        return self.socket.recv_json()

    def cancel_job(self, job):
        self.socket.send_json({
            'command': 'cancel-job',
            'job_id': job.id,
        })
        reply = self.socket.recv_json()
        if not reply['success']:
            log.error('APIClient.cancel_job(%r) failed: %s', job.id, reply['message'])
            raise APIError(reply['message'])
        log.info('Cancelled job %s', job.id)

    def zodburi(self):
        self.socket.send_json({
            'command': 'zodburi',
        })
        reply = self.socket.recv_json()
        return reply['uri']
