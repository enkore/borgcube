
from borg.repository import Repository
from borg.remote import RemoteRepository


def open_repository(repository):
    if repository.location.proto == 'ssh':
        # TODO construct & pass args for stuff like umask and remote-path
        return RemoteRepository(repository.location, exclusive=True, lock_wait=1)
    else:
        return Repository(repository.location.path, exclusive=True, lock_wait=1)


try:
    from setproctitle import setproctitle as set_process_name
except ImportError:
    def set_process_name(name):
        pass
