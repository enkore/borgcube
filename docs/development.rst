
Development
===========

Startup process
---------------

When a BorgCube command (e.g. ``borgcubed`` or ``borgcube-manage``) is invoked, then an entry point function
from `borgcube.entrypoints` is invoked. The very first thing done is to configure Django, which will
(indirectly) load the borgcube settings. When the settings are loaded the first phase of plugin discovery
begins:

Django applications specified by the ``borgcube0_apps`` entry point are added. Since this process
takes place before the logging system is initialized it can't use logging to facilitate debugging. Set
the ``BORGCUBE_DEBUG_APP_LOADING`` environment variable instead.

The ``borgcube0_apps`` entry point could look like this in the setup.py of a plugin::

    entry_points={
        # ...
        'borgcube0_apps': [
            'my_plugin_app = my_plugin.app',
        ]
    }

The left hand (my_plugin_app) is only for documentation; the dotted path on the right hand is used for the application.

After this the local settings file is executed to use the settings specified within it. Django will perform
it's initialization at this point, populating the applications registry (among other things, but this part is
most important, since only now ORM models become usable).

At this point regular `pluggy`_ plugins are discovered and loaded through their entry points.

Before the actual process is executed, the `borgcube.core.hookspec.borgcube_startup` hook is invoked with
the accordant parameters.

Anatomy of a Plugin
-------------------

The plugin system in BorgCube is based on the excellent `pluggy`_. The two important concepts involved in plugins are

1. plugins declare *themselves*, and are loaded automatically
2. you don't call us, we call you

**Ad 1.):** This is done through so-called *setuptools entry points*. We already touched on this topic above, and it
doesn't really get more complicated. A plugin declares in it's setup.py something like this::

    entry_points={
        'borgcube0': [
            'web_builtin_metrics = borgcube.web.core.builtin_metrics',
            ...
        ],
    }

There are three main elements here:

1. `borgcube0` is the name of the plugin API (*0* as in borgcube *0.x*)
2. `web_builtin_metrics` would be some descriptive name of your plugin
3. `borgcube.web.core.builtin_metrics` is the module in your plugin implementing borgcube hooks.

**Ad 2.):** A plugin implements *hooks*, which are called by borgcube at various spots. These are regular Python
functions, nothing special about them. This also means that there are no classes or interfaces or anything like
that you would need to implement - you just pick the hooks you need and implement them. For example, a "Hello World"
implementation might look like this::

    def borgcube_startup(db, process):
        print("Hello World, I'm in process", process)

To keep things concise you can leave out arguments you don't need in your hook implementation - they are all
passed like keyword-arguments, just that arguments you don't use won't raise an error::

    def borgcube_startup(process):
        print("Hello World, I'm in process", process)

If you save that into a file named *hello_plugin.py* and create an accompanying *setup.py*::

    from setuptools import setup

    setup(
        name='borgcube-hello-plugin',
        description='A plugin that says Hello World',
        py_modules=['hello_plugin'],
        install_requires=[
            'borgcube',
        ],
        entry_points={
            'borgcube0': [
                'hello_plugin = hello_plugin',
            ]
        }
    )

This is already a working plugin. You can *pip install path/to/the/directory* it and see it in action:

.. code-block:: console

    $ ls
    hello_plugin.py setup.py
    $ pip install .
    (Some relatively verbose output)
    $ borgcube-manage
    [2016-11-18 23:49:39,890] 13624 DEBUG    borgcube.utils: Loaded plugins: ..., hello_plugin, ...
    Hello World, I'm in process manage

    ...

    $ # To remove it again, type
    $ pip uninstall .


.. seealso::

    The *hookspec* modules specify the hooks used:

    - `borgcube.core.hookspec`
    - `borgcube.daemon.hookspec`
    - `borgcube.web.core.hookspec`

.. _pluggy: https://github.com/pytest-dev/pluggy

The database
------------

BorgCube uses the `ZODB`_ [#]_ object database, which is somewhat different from the Django ORM, while
providing relevant advantages to this particular project (it's not exactly the most popular database,
but it's mature, stable and very easy to use [#]_)

Instead of using migration scripts and migration state deduction to perform data migration on-the-fly
data migration through the `Evolvable` system.

The most important differences between RBDMS accessed through an ORM and the ZODB are (this section
is not project-specific)

1.  No explicit ORM is required, and fields don't have to be declared in advance. Object instances
    referred to by other objects are stored in the database as they are, including all attributes.

    Attributes starting with `_p_` (attributes related to handling persistence) and
    `_v_` (volatile attributes) are not preserved.

    Additionally this is further customizable through the standard `pickle`_ system,
    which is normally not required.

2.  There is no autocommit mode. Because the state of your objects and the transactions' snapshot
    are the same, autocommit wouldn't be particularly helpful -- the state of your objects would
    be continuously, uncontrollably be changed as other transactions commit.

3.  There is no `refresh_from_db <django.db.models.Model.refresh_from_db>` --
    ZODB ensures that the state of your objects exactly matches the state of the transaction.

4.  ZODB caches (aggressively). In ZODB every database connection has an associated cache, which
    contains already deserialized and alive objects. This makes read operations often as fast as
    just accessing a Python object (that already exists), because the database server is not
    contacted at all, and no additional object allocations need to be performed.

    Rollbacks are normally cheap, because only changed objects need to be re-fetched from the server.

    (In fact, a site will be able to serve common requests indefinitely with a dead database server,
    as long as no writes happen.)

5. The database only stores a *single* object. This object is the "root" object and all objects
   in the database are (have to be) reachable from the root, through an arbitrary number of objects
   referring to each other (including object cycles).

.. [#] Canonically ZODB stands for *Zope Object DataBase*, but it's okay if you call it
        *Ze Object Database* with a German accent ;)
.. [#] It's almost as old as PostgreSQL, and unlike *Strozzi 'the first' NoSQL* it's really
        not relational.

Use in BorgCube
+++++++++++++++

Locating and connecting to the database is handled transparently by the `data_root` function,
which returns a ready-to-use `DataRoot` instance. All other data follows from there. Plugins should
use the `DataRoot.plugin_data` instead of creating their own attributes on the DataRoot.

In `borgcube.web` view functions the transaction is reset before and after calling the view
through the `borgcube.web.core.middleware.transaction_middleware`, so any modifications to objects
in a view have to be explicitly committed. A simple example of this is the `repository_add` view:

.. code-block:: python
    :emphasize-lines: 11-12

    import transaction

    ...

    def repository_add(request):
        data = request.POST or None
        repository_form = Repository.Form(data)
        if data and repository_form.is_valid():
            repository = Repository(**repository_form.cleaned_data)
            data_root().repositories.append(repository)
            transaction.get().note('Added repository %s' % repository.name)
            transaction.commit()
            return redirect(repository_view, repository.oid)
        return TemplateResponse(request, 'core/repository/add.html', {
            'repository_form': repository_form,
        })

It's considered good practice to leave a meaningful transaction note, because in ZODB transactions
can be (selectively) undone, which is much easier if the transaction log makes it obvious
which transaction was the bad one. [#]_

Note how some functions bring their own transactions, eg. `Job.force_state` or `Job.update_state`.

.. _ZODB: http://www.zodb.org/en/latest/
.. _pickle: https://docs.python.org/3/library/pickle.html#pickling-class-instances


.. [#] We can also associate a user with a transaction, which is done by `borgcube.web` (TODO).
        This makes the transaction log of the ZODB similar to a free audit log.

Execution model
---------------

Now what's *that* you might ask? Since one of the main responsibilities of BC is to run
long-running tasks like creating, checking and pruning backups a component that orchestrates
this is needed. In BC this is done by a two-tiered approach:

The schedule

   It defines what should happen when on a calendric basis, eg. making daily backups.
   Internally this is implemented through `ScheduledActions <ScheduledAction>`, which
   usually create `Jobs <Job>`.

   Schedules are stored in the database and can be edited by administrators.

The queue

   It is a list of jobs that should run *right now*, it is never stored in the database
   and is, as an object, privately owned by the daemon process. It cannot be altered,
   except for cancelling jobs -- if a job is only queued, but not running yet, it is
   removed from the queue.

   The daemon ensures that new jobs added to the database are added to the queue as well,
   by checking for new jobs in every idle iteration.

   .. this could be done more efficiently (on-demand) by leveraging Z caches, but
      that would also mean re-doing the schedule evaluation (which *is* a TODO, actually),
      cf. seconds_until_next_occurence, which would also need to hook into the cache for
      schedule updates.

   The daemon performs a conflict check (whether a job can run given the set of currently
   running jobs) in FIFO order, and forks a worker for each job that can run.
