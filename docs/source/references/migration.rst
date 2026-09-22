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

Installing
----------

.. code-block:: diff

   -pip install isaacteleop[cloudxr]
   +pip install isaaccapture[cloudxr]

``pip install isaacteleop`` still resolves, to a distribution whose only content
is a redirect that depends on ``isaaccapture`` at the same version. The alias
lives in that distribution and nowhere else, so installing ``isaaccapture``
alone leaves ``import isaacteleop`` a plain ``ModuleNotFoundError``. Three more
consequences worth knowing:

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
  ``isaacteleop`` is typed ``Any``. It does not error, and it does not check
  anything either; autocomplete is gone. The alias promises runtime identity
  only. Migrate to ``isaaccapture`` to get the real types back.

The asset cache
---------------

The robot twin's cached meshes moved with the package name. A populated 1.5
cache is still on disk and is re-usable as is — the completeness marker and the
manifest digest both survive a move, so nothing is re-downloaded:

.. code-block:: console

   $ mkdir -p ~/.cache/isaaccapture
   $ cp -a ~/.cache/isaacteleop/. ~/.cache/isaaccapture/

``cp -a`` rather than ``mv``: once you have launched the twin under 1.6 the
destination already exists, and ``mv`` would move the old cache *inside* it
and exit 0. Delete ``~/.cache/isaacteleop`` afterwards if you want the space
back.

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

A detached CloudXR service started before the upgrade is still recognised by
``service status`` and ``service stop``, so it does not need to be stopped
first.
