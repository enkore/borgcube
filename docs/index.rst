Welcome to the BorgCube documentation
=====================================

.. warning::
   This is a work in progress. It is exceedingly likely that from this point in development to a release
   no upgrade path will be provided. This software is NOT READY FOR PRODUCTION USE. A lot of functionality is missing,
   and a lot of tests aren't written yet. There is NO SECURITY IMPLEMENTED yet in the web console.

BorgCube is a backup system built on `Borg Backup`_ featuring

- a web console for management
- scheduling and logging of backups and related work
- "pulling" backups from (untrusted) clients
- access control to your Borg repositories
- system/network-wide deduplication
- fast operation with no Borg cache syncs

Contents:

.. toctree::
   :maxdepth: 2

   development


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`


.. _`Borg Backup`: https://borgbackup.readthedocs.io/