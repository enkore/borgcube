
Command line
------------

import-archives
+++++++++++++++

Synopsis::

    borgcube-manage import-archives [--regex] client repository archive[-regex]

Import existing archives into BorgCube.

This makes existing archives show up in statistics as well as letting BC
consider them for pruning and access them for restore and other operations.

``client`` should be the hostname of a client, ``repository`` should be the
name or URL of a repository, or the ID (or a prefix thereof) of a repository.

``archive`` refers to a single archive in the repository, or multiple archives
if it's a regex and ``--regex`` is specified.


borgcubed
+++++++++

Synopsis::

    borgcubed

Starts the BorgCube daemon in the foreground. Does not accept any options.

borgcube-gandalf
++++++++++++++++

Synopsis::

    borgcube-gandalf

Interactive wizard for initial setup.
