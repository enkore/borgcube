
BorgCube
========

NOTE: This is a work in progress. It is exceedingly likely that from this point in development to a release
no upgrade path will be provided. This software is NOT READY FOR PRODUCTION USE. A lot of functionality is missing,
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

- Deduplication is still done on the clients, saving time and
  bandwidth. Inadvertedly this means that all clients know about all
  chunks in the underlying repository (see
  [convergent encryption](https://en.wikipedia.org/wik)).

- The server is responsible for encryption (note: due to current
  internal limitations in Borg it's not possible to avoid encrypting
  on the clients also if the repository is encrypted**), cache
  maintenance and storage and logging/error reporting.

- Clients don't need Borg installed; BorgCube can deploy an appropiate binary on the fly.

- Multiple backups into the same repository at once

\** to make this happen we need two modes in Borg which share the *same* keyed MAC for the chunk ID.

Inner workings
--------------

- Web console written on top of Django
- Redis is used as a general purpose message bus
- Data is mostly stored in SQL database
- Live progress information is streamed via web sockets into the frontend
- Background workers are used for tasks that may take longer (accessing repositories etc)

- SSH server required, SSH server is also required on the clients.
- BorgCube doesn't include SSH key management: just deploy the keys as usual.

To make a backup:

1. The backup is marked as in progress in the DB; this reserves the archive name and also allocates a UUID for the process.
2. BorgCube rsync's (over SSH) the current cache for the repository to the client.
3. BorgCube generates fresh encryption keys (see above; borg limitation)
3. It SSHs into the client (via a background worker) and starts a "borg create" process, targeting the BorgCube server and user, like this:

        borg create [options] ssh://borgcube@bc.enkore.de/[UUID]

    The background worker shovels log data into the DB from here on
    out. It also parses progress output and broadcasts it via redis;
    an authorized user may receive it over a WebSocket

4. The authorized_keys file however contains a forced\_command, executing the BorgCube-RP (reverse proxy) component.
5. This component then fetches the backup data from the DB via the UUID specified in the path.
6. It then connects to the actual repository and loads the actual key file
7. Incoming objects are verified with the chunk ID to avoid bogus writes from a client
8. Deletes are only executed for checkpoint archives belonging to this job

  - PUT [archive obj], PUT [manifest with checkpoint], COMMIT, ... DELETE [checkpoint archive obj], PUT [newer archive obj], ...

9. The manifest is handled specially: the client only see's it's own archives from this very job. Writing is interecepted and specially handled as well.

  - A great deal of care is needed here to fool Borg's cache sync logic here.

10. The client can't read data except the manifest (see 9.)
11. Special operations are prohibited
12. Any violation of 10., 11. 8. or 7. will terminate the job
13. When done the job state is updated again.
14. The server cache is updated.
15. The cache on the client is removed.

---

Extracting onto a client can be done in a similar way, just the set of operations is different.
