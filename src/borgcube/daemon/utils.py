import os
import threading
from queue import Queue, Empty
from wsgiref.simple_server import WSGIServer

from django.conf import settings


class ThreadPoolWSGIServer(WSGIServer):
    """
    Mixin to use a fixed pool of threads to handle requests.
    .. note::
       When shutting down the server, please ensure you call this mixin's
       `join()` to shut down the pool along with the server's `shutdown()`
       method. The order in which these are performed is not significant,
       but both actions must be performed.
    """

    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True,
                 pool_size=5, timeout_on_get=0.5):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        # Size of pool.
        self.pool_size = pool_size
        # How long to wait on an empty queue, in seconds. Can be a float.
        self.timeout_on_get = timeout_on_get
        self._request_queue = Queue(self.pool_size)
        # This beastie serves a different purpose than __shutdown_request
        # and __is_shut_down: those are superprivate so we can't touch them,
        # and even if we could, they're not really useful in shutting down
        # the pool.
        self._shutdown_event = threading.Event()
        for _ in range(self.pool_size):
            thread = threading.Thread(target=self.process_request_thread, daemon=True)
            thread.start()

    def process_request_thread(self):
        """Same as in BaseServer, but as a thread."""
        while True:
            try:
                request, client_address = self._request_queue.get(
                    timeout=self.timeout_on_get,
                )
            except Empty:
                # You wouldn't believe how much crap this can end up leaking,
                # so we clear the exception.
                if self._shutdown_event.isSet():
                    return
                continue
            try:
                self.finish_request(request, client_address)
                self.shutdown_request(request)
            except:
                self.handle_error(request, client_address)
                self.shutdown_request(request)
            self._request_queue.task_done()

    def process_request(self, request, client_address):
        """Queue the given request."""
        self._request_queue.put((request, client_address))

    def join(self):
        """Wait on the pool to clear and shut down the worker threads."""
        # A nicer place for this would be shutdown(), but this being a mixin,
        # that method can't safely do anything with that method, thus we add
        # an extra method explicitly for clearing the queue and shutting
        # down the workers.
        self._request_queue.join()
        self._shutdown_event.set()


def get_socket_addr(suffix):
    return settings.SOCKET_PREFIX.format(euid=os.geteuid()) + '-' + suffix
