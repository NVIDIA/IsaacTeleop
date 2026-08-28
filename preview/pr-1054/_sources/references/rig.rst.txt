.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

.. _rig-launcher:

Rig Launcher
============

A typical Isaac Teleop setup is three processes on one machine: the CloudXR
runtime, one or more **producer** plugins that publish device data, and one or
more **consumer** apps (a Python ``TeleopSession`` script or a C++ example
binary) that read the streams. Such a configured set is a *rig* — the same
shape serves demos, production teleop, and data collection.
``isaacteleop.rig`` starts a rig in a single tmux session from a small YAML
file, instead of you juggling three terminals by hand:

.. code-block:: bash

   # from the Teleop repository root
   python -m isaacteleop.rig rigs/se3_tracker.yaml

The module ships in the ``isaacteleop`` wheel; the rig files are part of the
source checkout under ``rigs/`` (they reference ``install/`` binaries, so they
only make sense next to a built tree).

.. contents:: Sections
   :local:
   :depth: 1
   :backlinks: none

Prerequisites
-------------

- ``tmux`` installed (``sudo apt install tmux``).
- A built and installed Teleop tree (see :ref:`install-isaacteleop-pip-package`
  and the build reference) — the rig references binaries under
  ``install/plugins/`` and ``install/examples/``.
- The ``isaacteleop`` wheel installed in the **current** Python environment.
  tmux panes do not inherit your venv; the launcher bakes the absolute path of
  its own interpreter (and your ``PYTHONPATH``, if set) into the pane commands,
  so whatever environment you launch from is the one the rig runs in.

Run a rig
---------

.. code-block:: bash

   # from the Teleop repository root
   python -m isaacteleop.rig rigs/se3_tracker.yaml

   # a CloudXR runtime is already running elsewhere (skip the runtime pane):
   python -m isaacteleop.rig rigs/se3_tracker.yaml --no-runtime

What happens:

1. **Preflight** — the launcher verifies tmux is available, the referenced
   binaries exist and are executable (with the exact ``cmake`` remedy if not),
   and the interpreter can import ``isaacteleop.cloudxr``. Nothing is created
   until preflight passes.
2. **Runtime pane starts immediately** (a slim full-width strip on top —
   25% of the window; it only prints status lines — with the worker panes
   tiled below). It runs ``python -m isaacteleop.cloudxr --accept-eula`` by
   default and prints the web-client URL. The runtime is a **host
   singleton** — one per machine.
3. **Worker panes load the CloudXR environment automatically.** Each
   producer/consumer pane waits (up to two minutes) for the runtime's
   ``runtime_started`` sentinel, then runs
   ``source <install-dir>/run/cloudxr.env`` so ``XR_RUNTIME_JSON`` and
   friends point at the runtime — you never source it by hand. The install
   dir follows the runtime command's ``--cloudxr-install-dir`` (default
   ``~/.cloudxr``).
4. **Producer/consumer panes then run their commands automatically.** As
   soon as the CloudXR environment is loaded, each pane prints a banner
   (``[producer: ...] running: <command>``) and runs its command — no
   :kbd:`Enter` needed. When the command exits, the pane reports
   ``[rig] command exited with status N — press Enter to rerun`` and drops
   to an interactive shell with the same command pre-typed at the prompt.
   Anything that calls ``xrGetSystem`` before a headset connects exits with
   ``Failed to get OpenXR system`` — so if a pane's app started before you
   connected the headset to the printed URL, connect it and press
   :kbd:`Enter` in that pane to rerun. If the runtime never comes up (or
   its environment fails to load), the pane does *not* run the command; it
   prints a remedy and leaves the command pre-typed instead.
5. The launcher then attaches (from a plain shell) or switches your current
   client (from inside tmux — no nesting).

Re-running the same rig just switches to the existing session; it does
**not** re-apply ``--no-runtime`` or pick up edits to the rig file. Start
over with:

.. code-block:: bash

   python -m isaacteleop.rig rigs/se3_tracker.yaml --kill

which kills the rig's tmux session and every process in it (equivalent to
``tmux kill-session -t se3_tracker``, without needing to know the session
name). Killing a rig that is not running is a no-op.

The rig YAML
------------

``rigs/se3_tracker.yaml`` is the annotated exemplar — copy it to write your
own:

.. code-block:: yaml

   name: se3_tracker              # rig id AND tmux session name (letters/digits/-/_)
   description: CloudXR runtime + SE3 controller tracker plugin + pose printer
   cwd: ..                        # pane working dir, relative to this file
   params:                        # shared values, substituted into the commands below
     hand: right
     collection_id: se3_tracker   # defined ONCE, referenced by both sides below
   # runtime: optional full-command override for the runtime pane; default:
   #   {python} -m isaacteleop.cloudxr --accept-eula
   producers:                     # publish device data into the runtime
     - name: se3 tracker plugin (requires headset + controller)
       command: "install/plugins/controller_se3_tracker/controller_se3_tracker_plugin {hand} {collection_id}"
   consumers:                     # read the streams — a TeleopSession script or a C++ binary
     - name: se3 printer (requires headset)
       command: "install/examples/schemaio/se3_printer {collection_id}"

``rigs/full_body.yaml`` shows the other supported shape — no ``producers``
key, because its consumers read the tracking data directly from the runtime,
so there is no ``collection_id`` to rendezvous on.

Top-level keys:

.. list-table::
   :header-rows: 1
   :widths: 18 12 70

   * - Key
     - Required
     - Meaning
   * - ``name``
     - yes
     - Rig id **and** tmux session name. Letters, digits, ``-``, ``_`` only.
   * - ``description``
     - no
     - Free text, printed when the session is created.
   * - ``cwd``
     - no
     - Working directory for every pane and the base for relative command
       paths, resolved relative to the YAML file's directory (default: the
       YAML's directory).
   * - ``params``
     - no
     - Flat mapping of ``{placeholder}`` values shared by the commands
       below — the rig file is the single source of configuration; edit it
       (and relaunch with ``--kill``) to change them.
   * - ``runtime``
     - no
     - Full-command override for the runtime pane (e.g. to add
       ``--host-client`` or a different device profile). Default:
       ``{python} -m isaacteleop.cloudxr --accept-eula``.
   * - ``producers`` / ``consumers``
     - at least one entry total
     - Lists of ``{name, command}`` entries. ``name`` is free text shown in
       the pane title (a good place for hardware prerequisites); ``command``
       is a shell string run verbatim in the pane.

Commands are plain shell strings. ``{python}`` always expands to the absolute
path of the launching interpreter; every other ``{placeholder}`` must be
declared under ``params`` (literal braces are written ``{{`` / ``}}``).
Unknown top-level keys, unknown entry keys, and unknown placeholders are hard
errors — a typo fails loudly at load time instead of misbehaving in a pane.

.. important::

   In a rig with both producers and consumers, the two sides rendezvous on a
   shared ``collection_id``, and a mismatch is **silent no-data** by design.
   Define it once under ``params`` and reference it as ``{collection_id}`` in
   every command — then one edit in one place changes both sides together.

.. warning::

   Python ``TeleopSession`` example scripts launch their **own** CloudXR
   runtime by default (``--launch-cloudxr-runtime`` defaults to true). The
   runtime is a host singleton, so auto-running such a consumer kills the
   runtime pane — the headset drops and every producer stalls. Always add
   ``--no-launch-cloudxr-runtime`` to Python consumer commands in a rig; the
   launcher prints a warning (and repeats it in the pane banner) when a
   command looks like it is missing the flag.

   See :ref:`dedicated-cloudxr-runtime` for more on standalone runtime
   workflows.

Troubleshooting
---------------

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Symptom
     - Likely cause
   * - ``... not found or not executable — build and install first``
     - The rig references ``install/`` binaries that are not built yet; run
       the printed ``cmake`` commands.
   * - ``cannot import 'isaacteleop.cloudxr'``
     - You launched from an environment without the ``isaacteleop`` wheel;
       activate the right venv (or ``pip install install/wheels/isaacteleop-*.whl``).
   * - A worker pane sits idle without running its command
     - The pane is still waiting for the runtime's ``runtime_started``
       sentinel; check the runtime pane. After the (two-minute) wait times
       out, the pane prints a remedy and leaves the command pre-typed.
   * - ``[cloudxr] runtime is up but loading ... failed``
     - The runtime came up but its ``cloudxr.env`` could not be sourced;
       the pane does not run its command. Check the error printed above
       the message, ``source`` the file as the message says, then press
       :kbd:`Enter` — the command is already pre-typed.
   * - ``[rig] command exited with status ...`` right after launch
     - The app auto-ran before the headset connected (classic:
       ``Failed to get OpenXR system``); connect the headset to the
       runtime's URL, then press :kbd:`Enter` in the pane — the command is
       already pre-typed at the prompt.
   * - Runtime pane dies when a consumer starts
     - The consumer self-launched a second runtime; add
       ``--no-launch-cloudxr-runtime`` to its command in the rig.
   * - Edits to the rig file seem ignored
     - The session already existed; relaunch after
       ``python -m isaacteleop.rig <rig.yaml> --kill``.
