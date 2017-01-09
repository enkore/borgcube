
BorgCube
========

.. image:: https://readthedocs.org/projects/borgcube/badge/?version=latest
   :target: http://borgcube.readthedocs.io/en/latest/?badge=latest
   :alt: Documentation Status

**WARNING: This is a work in progress.** It is exceedingly likely that from this point in development to a release
no upgrade path will be provided. This software is **NOT READY FOR PRODUCTION USE**. A lot of functionality is missing,
and a lot of tests aren't written yet. There is NO SECURITY IMPLEMENTED yet in the web console.

NOTE: At this time I will not take pull requests.

A backup system built on Borg.

Scope
-----

- Web console for management
- Backups are pulled from clients
- Scheduling, logging.
- Lightweight, untrusted clients:

  - They can't manipulate the repository
  - They don't know where the repository is
  - They don't get encryption keys
  - They can't read backups (of other clients and also themselves)
  - They don't need to maintain a Borg cache
  - They don't have to encrypt (if any of the BLAKE2 key types are used)

- Deduplication is still done on the clients, saving time and
  bandwidth. Inadvertedly this means that all clients know about the hash / MAC of all
  chunks in the underlying repository.

- The server is responsible for encryption, cache
  maintenance and storage and logging/error reporting.

- Clients don't need Borg installed; BorgCube can deploy an appropriate binary on the fly.

- Multiple backups into the same repository at once

Inner workings
--------------

- Web console written on top of Django
- Data is mostly stored in SQL database (per-job logs in plain text files)
- Live progress information is streamed via web sockets into the frontend
- Background workers are used for tasks that may take longer (accessing repositories etc)
- Workers are coordinated by borgcubed. Frontend and borgcubed talk via ZeroMQ (planned: UDS, automatic authentication).
- SSH server on the BorgCube server and on all clients required.
- BorgCube doesn't include SSH key management: just deploy the keys as usual.
