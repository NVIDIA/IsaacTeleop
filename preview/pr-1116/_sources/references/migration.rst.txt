.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Migrating to ``isaaccapture``
=============================

In 1.6 the Python import package and the distribution were both renamed from
``isaacteleop`` to ``isaaccapture``. ``import isaacteleop`` keeps working for
now through a compatibility distribution, which **will be removed in 1.9**.

.. warning::

   1.9 is inside the 1.x series, so a pin such as ``isaacteleop<2`` or
   ``isaacteleop~=1.6`` does **not** hold the alias: it resolves to 1.8, the last
   release that ships one, and upgrades stop there with no diagnostic.
   ``isaacteleop<1.9`` resolves to that same release and says so. Only moving to
   ``isaaccapture`` ends the problem.

In short
--------

#. Upgrade with ``pip install -U isaacteleop[...]``, **not** by installing
   ``isaaccapture`` beside it -- see :ref:`migration-upgrading`.
#. Rewrite ``isaacteleop`` to ``isaaccapture`` in imports and ``python -m``
   commands, but **not** ``isaacteleop_examples``.
#. Rename the dependency in your own ``pyproject.toml`` / ``requirements.txt``.
#. Move the robot-twin asset cache and its two override variables, if you use them.

.. _migration-upgrading:

Upgrading an existing install
-----------------------------

``isaacteleop`` and ``isaaccapture`` are different distributions, so pip will not
replace one with the other. Upgrade through the **old** name and pip removes the
1.5 tree for you:

.. code-block:: console

   $ pip install -U "isaacteleop[cloudxr]"     # 1.5 tree removed, alias installed

Installing ``isaaccapture`` beside an existing ``isaacteleop`` 1.5 instead leaves
both on disk -- two complete first-party trees, two copies of every compiled
extension. ``import isaacteleop`` then resolves to the **stale 1.5 tree** rather
than to the alias, with no deprecation notice to say so, and a half-migrated
process holds two registries of the same pybind11 types. If that has already
happened, ``pip uninstall -y isaacteleop`` and reinstall whichever of the two you
meant.

On a machine with no ``isaacteleop`` installed, ``pip install isaaccapture`` is
all you need; ``import isaacteleop`` is then a plain ``ModuleNotFoundError``.

Imports
-------

.. code-block:: diff

   -import isaacteleop
   -from isaacteleop.teleop_session_manager import DeviceState
   +import isaaccapture
   +from isaaccapture.teleop_session_manager import DeviceState

Every submodule keeps its name; only the top-level package changes. Both names
resolve to the same module objects until 1.9, so a partially migrated process
shares state, singletons and extension registrations rather than loading two
copies.

The same rename applies to ``python -m`` entry points, for example
``python -m isaaccapture.cloudxr.service run``.

.. warning::

   ``isaacteleop_examples`` is a **different** package and was not renamed. A
   repo-wide substitution breaks every ``python -m isaacteleop_examples.*``
   command, and the alias deliberately declines that name, so the failure is a
   bare ``ModuleNotFoundError`` with no notice attached. Rewrite ``isaacteleop``
   only where it stands alone.

What importing the old name does
--------------------------------

Until 1.9 the old name still resolves, but it is not silent:

- It raises a ``DeprecationWarning`` on the first import in a process.
- When the default filters hide that warning -- which is every import not made
  from ``__main__``, including every ``python -m`` -- the same text is printed to
  stderr instead, prefixed with the importing ``file:line``.
- Under ``-W error::DeprecationWarning``, or a pytest
  ``filterwarnings = ["error"]``, the import **raises**. A suite that sets this
  collects nothing until the imports are renamed.

To silence both channels while you migrate, filter on the message. A
module-scoped filter does not work: the warning is reported against the line that
imported, not against ``isaacteleop``.

.. code-block:: console

   $ python -W "ignore:The 'isaacteleop' import package:DeprecationWarning" -m yourapp

.. code-block:: toml

   [tool.pytest.ini_options]
   filterwarnings = ["ignore:The 'isaacteleop' import package:DeprecationWarning"]

Installing
----------

.. code-block:: diff

   -pip install isaacteleop[cloudxr]
   +pip install isaaccapture[cloudxr]

``pip install isaacteleop`` still resolves, to a distribution whose only content
is a redirect that depends on ``isaaccapture`` at the same version. Every extra
is mirrored, so ``isaacteleop[cloudxr]`` installs ``isaaccapture[cloudxr]``.
Three more consequences worth knowing:

- A ``--no-deps`` install of ``isaacteleop`` installs the redirect **and nothing
  else**, and raises ``ImportError`` on first import. Isaac Sim's
  ``deps/pip_teleop.toml`` and Isaac Lab's ``isaaclab_teleop`` both pin
  ``isaacteleop``; they must name ``isaaccapture`` before their next version
  bump.
- **From source, how you get the alias depends on the path.** The classic CMake
  flow builds both wheels into ``install/wheels/``, so name both there, and
  running straight off the build tree needs both staged roots on ``PYTHONPATH``.
  ``pip install -e .`` resolves the alias from the source tree; ``pip install .``
  does not, because the wheel it builds is the real distribution and ships one
  package. The commands are in
  :doc:`/getting_started/build_from_source/index` and :doc:`build`.
- A ``sys.meta_path`` finder is invisible to a type checker, so everything under
  ``isaacteleop`` is typed ``Any``: autocomplete is gone, and nothing is checked.
  mypy accepts it; **pyright reports every submodule import as unresolved**
  (``reportMissingImports``) because the stub has no submodules to find. The
  alias promises runtime identity only. Migrate to ``isaaccapture`` to get the
  real types back.

Logging
-------

Loggers are named after the module they live in, and the alias hands back the
real module, so the whole hierarchy moved to ``isaaccapture.*`` even for code
that still imports the old name. No alias can reach a string key, so a
``dictConfig`` or ``getLogger`` call naming ``isaacteleop`` silently stops
matching -- the logger is created, and nothing ever logs to it:

.. code-block:: diff

   -logging.getLogger("isaacteleop.cloudxr").setLevel(logging.DEBUG)
   +logging.getLogger("isaaccapture.cloudxr").setLevel(logging.DEBUG)

The asset cache
---------------

The robot twin's cached meshes moved with the package name. A populated 1.5
cache is still on disk and is re-usable as is -- the completeness marker and the
manifest digest both survive a move, so nothing is re-downloaded:

.. code-block:: console

   $ mkdir -p ~/.cache/isaaccapture
   $ cp -a ~/.cache/isaacteleop/. ~/.cache/isaaccapture/

``cp -a`` rather than ``mv``: once you have launched the twin under 1.6 the
destination already exists, and ``mv`` would move the old cache *inside* it
and exit 0. Delete ``~/.cache/isaacteleop`` afterwards if you want the space
back. If ``XDG_CACHE_HOME`` is set, both paths are under it rather than
``~/.cache``.

The two override variables moved with it. They are no longer read under their
old names, and ``isaaccapture.viz.robot`` logs a warning if it finds one set:

.. list-table::
   :header-rows: 1

   * - Old
     - New
   * - ``ISAACTELEOP_SO101_ASSETS``
     - ``ISAACCAPTURE_SO101_ASSETS``
   * - ``ISAACTELEOP_REBOT_ASSETS``
     - ``ISAACCAPTURE_REBOT_ASSETS``

These two are the only environment variables this release renames. The
``ISAAC_TELEOP_*`` variables documented elsewhere -- the CloudXR runtime
switches among them -- keep their names.

The detached CloudXR service
----------------------------

A detached service started before the upgrade is still recognised by
``service status`` and ``service stop``, so it does not need to be stopped
first: 1.6 matches the old module name in its ``/proc`` command line as well as
the new one.

.. warning::

   That only works in one direction. A service started under 1.6 is **not**
   recognised by a 1.5 CLI, which cannot know the new name. If you roll back,
   stop the service first -- otherwise ``service stop`` reports that nothing is
   running, exits 0, and leaves a runtime holding the GPU.
