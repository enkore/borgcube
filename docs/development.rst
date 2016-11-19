
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
