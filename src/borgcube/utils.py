
from borg.repository import Repository
from borg.remote import RemoteRepository


def open_repository(repository):
    if repository.location.proto == 'ssh':
        # TODO construct & pass args for stuff like umask and remote-path
        return RemoteRepository(repository.location, exclusive=True)
    else:
        return Repository(repository.location.path, exclusive=True)
