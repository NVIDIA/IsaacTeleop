.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

CloudXR Runtime
===============

The **CloudXR runtime** is what actually stream sensor data and visual data
between various I/O devices (e.g. XR headset, gloves, etc) and Isaac Teleop.
They can be started two ways, both on top of the same code path:

- **CLI** — ``python -m isaacteleop.cloudxr`` from a dedicated terminal.
- **Python API** — :class:`CloudXRLauncher`, for embedding the runtime
  inside an existing Python application (for example an Isaac Sim or
  Isaac Lab script) so no second terminal is required.

This page is the reference for both.  For a first-time walkthrough with
screenshots, start at :doc:`../getting_started/quick_start`; come back
here when you need the programmatic API, a full list of environment
variables, or troubleshooting detail.

Two ways to run
---------------

Command line
^^^^^^^^^^^^

.. code-block:: bash

   python -m isaacteleop.cloudxr [options]

Flags:

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Flag
     - Description
   * - ``--cloudxr-install-dir PATH``
     - CloudXR install directory.  Default: ``~/.cloudxr``.
   * - ``--cloudxr-env-config PATH``
     - Optional ``KEY=value`` file whose entries override the default
       CloudXR environment variables.  See `Environment variables`_.
   * - ``--accept-eula``
     - Accept the NVIDIA CloudXR EULA non-interactively (CI,
       containers, unattended scripts).
   * - ``--setup-oob``
     - Enable the OOB teleop control hub and USB-adb headset
       automation.  See :doc:`oob_teleop_control`.

Python API
^^^^^^^^^^

.. code-block:: python

   from isaacteleop.cloudxr import CloudXRLauncher

   with CloudXRLauncher(accept_eula=True) as launcher:
       # runtime + WSS proxy are running
       ...

The CLI above is a thin wrapper around this class; every flag maps
directly to a constructor argument.

``CloudXRLauncher``
-------------------

.. code-block:: python

   class CloudXRLauncher:
       def __init__(
           self,
           install_dir: str = "~/.cloudxr",
           env_config: str | pathlib.Path | None = None,
           accept_eula: bool = False,
           setup_oob: bool = False,
       ) -> None: ...

The launcher starts work immediately in ``__init__``: it resolves env
configuration, verifies the EULA, cleans up any stale sentinel files,
spawns the runtime subprocess, waits up to **30 seconds** for readiness,
and then starts the WSS proxy thread.  Construction therefore returns
either with a fully running runtime or with a :class:`RuntimeError`.

Constructor arguments
^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Argument
     - Description
   * - ``install_dir``
     - CloudXR install directory.  Used to resolve the run directory
       (``<install_dir>/run``) and log directory
       (``<install_dir>/logs``).  The path is expanded (``~``) and made
       absolute.
   * - ``env_config``
     - Optional path to a ``KEY=value`` env file.  Values undergo
       ``$VAR`` and ``~`` expansion.  Keys that are reserved by the
       runtime (``XR_RUNTIME_JSON``, ``XRT_NO_STDIN``,
       ``NV_CXR_RUNTIME_DIR``, ``NV_CXR_OUTPUT_DIR``) are ignored with a
       warning.
   * - ``accept_eula``
     - If ``True``, accept the CloudXR EULA non-interactively and write
       the acceptance marker.  If ``False`` and the marker is absent,
       the user is prompted on stdin; a non-TTY stdin causes the prompt
       to fail and :class:`RuntimeError` is raised.  CI, containers,
       and any unattended caller should pass ``True``.
   * - ``setup_oob``
     - Enable the OOB teleop control hub in the WSS proxy.  See
       :doc:`oob_teleop_control` for details.

Methods and properties
^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Member
     - Description
   * - ``stop() -> None``
     - Signal the WSS proxy to shut down and terminate the runtime
       process group (SIGTERM, then SIGKILL after 10 s).  Safe to call
       multiple times, including when nothing is running.  Raises
       :class:`RuntimeError` only if termination fails; the process
       handle is retained so callers can retry or inspect it.
   * - ``health_check() -> None``
     - Raise :class:`RuntimeError` if the runtime subprocess has
       exited, or if the WSS proxy thread has stopped.  Returns
       silently when both are alive.  Call periodically from an
       embedding app to notice a crashed runtime.
   * - ``wss_log_path`` (property)
     - :class:`pathlib.Path` to the current WSS proxy log file, or
       ``None`` if the proxy has not been started yet.
   * - ``__enter__`` / ``__exit__``
     - Context-manager protocol.  ``__exit__`` calls :meth:`stop`.

At-exit cleanup
^^^^^^^^^^^^^^^

The launcher registers :meth:`stop` with :mod:`atexit` on first
successful construction, so the runtime is stopped even if the
embedding process exits abnormally (unhandled exception, SystemExit).
An explicit :meth:`stop` call, or exiting a ``with`` block, still runs
cleanup immediately — the ``atexit`` hook is a safety net, not a
substitute.

Error semantics
^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - ``RuntimeError`` from
     - Meaning
   * - ``__init__``
     - EULA refused, or runtime did not reach readiness within
       ``RUNTIME_STARTUP_TIMEOUT_SEC`` (30 s).  Any partial state is
       torn down before raising and the exception message includes a
       diagnostic tail from the runtime stderr log and the most recent
       ``cxr_server`` log.
   * - ``stop()``
     - The runtime process group did not exit after SIGTERM and
       SIGKILL.  The ``Popen`` handle is retained so the caller can
       retry or inspect it.
   * - ``health_check()``
     - Runtime subprocess exited, or WSS proxy thread stopped.  Call
       :meth:`stop` to clean up the surviving component before
       constructing a new launcher.

Integration pattern
-------------------

Minimal
^^^^^^^

The simplest embedding is a ``with`` block around the code that needs
the runtime:

.. code-block:: python

   from isaacteleop.cloudxr import CloudXRLauncher

   with CloudXRLauncher(accept_eula=True) as launcher:
       run_teleop_session()  # your app's main work

On exit (normal or exception) the runtime subprocess and WSS proxy are
torn down.

Realistic embedding
^^^^^^^^^^^^^^^^^^^

A longer-running application typically wants to (a) detect a crashed
runtime during the session, (b) respond to SIGINT/SIGTERM cleanly, and
(c) guarantee teardown even if the signal handler never fires.  The
pattern below mirrors what ``python -m isaacteleop.cloudxr`` does
internally:

.. code-block:: python

   import signal
   import time
   from isaacteleop.cloudxr import CloudXRLauncher

   launcher = CloudXRLauncher(
       install_dir="~/.cloudxr",
       env_config=None,
       accept_eula=True,
   )
   try:
       stop = False

       def _on_signal(sig, frame):
           nonlocal stop
           stop = True

       signal.signal(signal.SIGINT, _on_signal)
       signal.signal(signal.SIGTERM, _on_signal)

       while not stop:
           launcher.health_check()  # raises if runtime or proxy died
           do_one_tick_of_your_app()
           time.sleep(0.1)
   finally:
       launcher.stop()

Notes:

- ``health_check()`` is cheap (it polls a ``Popen`` and checks a thread
  flag); calling it every tick is fine.
- The ``finally`` clause is redundant with the :mod:`atexit` hook under
  normal exits, but keeps teardown deterministic for embedders that
  rely on ordered shutdown.
- Construction is synchronous and blocks the calling thread for up to
  30 s while waiting for the runtime to become ready.  Do not call it
  from inside a running asyncio event loop — use
  :func:`asyncio.to_thread` (or construct before the loop starts).
  The WSS proxy itself runs on its own thread with an independent
  event loop.

Files and logs
--------------

Everything the runtime persists lives under ``install_dir`` (default
``~/.cloudxr``):

::

   ~/.cloudxr/
   ├── openxr_cloudxr.json         # OpenXR runtime manifest (staged from the SDK)
   ├── libopenxr_cloudxr.so        # OpenXR runtime library (staged from the SDK)
   ├── run/
   │   ├── cloudxr.env             # final KEY=value env, source this in other terminals
   │   ├── eula_accepted           # EULA acceptance marker
   │   ├── runtime_started         # sentinel — created once the runtime is ready
   │   ├── ipc_cloudxr             # UNIX socket used between Monado and CloudXR
   │   ├── monado.pid              # Monado PID (for stale-process cleanup)
   │   └── cloudxr.pid             # CloudXR native service PID
   └── logs/
       ├── runtime_stderr.log      # Python + Vulkan/GPU init diagnostics
       ├── cxr_server.<ts>.log     # native CloudXR server log (one per run)
       └── wss.<ts>.log            # WSS proxy log (one per run)

Sourcing the env file
^^^^^^^^^^^^^^^^^^^^^

To run another process (e.g. Isaac Sim) against this runtime from a
different terminal, source the env file:

.. code-block:: bash

   source ~/.cloudxr/run/cloudxr.env

This sets ``XR_RUNTIME_JSON``, ``NV_CXR_RUNTIME_DIR``,
``NV_CXR_OUTPUT_DIR``, and the user-configurable CloudXR variables so
an OpenXR client finds the CloudXR runtime.

Stale-runtime cleanup
^^^^^^^^^^^^^^^^^^^^^

If the previous runtime crashed without cleaning up, the sentinel
files may still be present.  On startup the launcher:

1. Looks for ``run/ipc_cloudxr``.  If present, uses ``fuser -k -TERM``
   to ask any process still holding the socket to exit.
2. Removes ``run/ipc_cloudxr``, ``run/runtime_started``,
   ``run/monado.pid``, and ``run/cloudxr.pid``.
3. Starts the new runtime in a fresh process group.

If construction still fails with "runtime failed to start within 30 s",
check ``logs/runtime_stderr.log`` and the newest ``logs/cxr_server.*.log``.

Environment variables
---------------------

Runtime
^^^^^^^

These control the CloudXR runtime itself.  Defaults come from
:class:`EnvConfig`; override via ``--cloudxr-env-config`` (CLI) or
``env_config=`` (API).

.. list-table::
   :header-rows: 1
   :widths: 30 22 48

   * - Variable
     - Default
     - Description
   * - ``NV_CXR_FILE_LOGGING``
     - ``true``
     - Redirect runtime stdout/stderr to files under ``logs/``.  Set
       ``false`` to keep native output on the terminal (useful for
       debugging; disables ``runtime_stderr.log``).
   * - ``NV_CXR_ENABLE_PUSH_DEVICES``
     - ``true``
     - Enable OpenXR push-device extensions used by Isaac Teleop.
   * - ``NV_CXR_ENABLE_TENSOR_DATA``
     - ``true``
     - Enable tensor-data streaming channel.
   * - ``NV_DEVICE_PROFILE``
     - ``auto-webrtc``
     - CloudXR device profile.  See the CloudXR SDK docs for valid
       values.
   * - ``CXR_INSTALL_DIR``
     - *(from ``install_dir``)*
     - Resolved automatically; subprocesses inherit it to locate the
       run/log directories.

The following are resolved by the launcher from ``install_dir`` and
**cannot** be overridden from the env file (they are silently dropped
with a warning if you try):

- ``XR_RUNTIME_JSON`` — path to the staged ``openxr_cloudxr.json``.
- ``XRT_NO_STDIN`` — always ``true``; disables Monado stdin.
- ``NV_CXR_RUNTIME_DIR`` — the ``run/`` directory under ``install_dir``.
- ``NV_CXR_OUTPUT_DIR`` — the ``logs/`` directory under ``install_dir``.

``LD_LIBRARY_PATH``
^^^^^^^^^^^^^^^^^^^

The launcher prepends the bundled SDK directory to ``LD_LIBRARY_PATH``
before spawning the subprocess so that ``libcloudxr.so`` and
``libopenxr_cloudxr.so`` are found.  The runtime also loads
``libcloudxr.so`` with ``RTLD_DEEPBIND`` to prevent symbol conflicts
with host applications that have already loaded an incompatible
OpenSSL.

WSS proxy and OOB
^^^^^^^^^^^^^^^^^

The WSS proxy and OOB hub honor their own environment variables
(``PROXY_PORT``, ``CONTROL_TOKEN``, ``TELEOP_STREAM_SERVER_IP``, …).
Those are documented with the hub they configure; see
:doc:`oob_teleop_control`.

EULA
----

The first run prompts the user to accept the `NVIDIA CloudXR EULA
<https://github.com/NVIDIA/IsaacTeleop/blob/main/deps/cloudxr/CLOUDXR_LICENSE>`_.
Acceptance is recorded at ``~/.cloudxr/run/eula_accepted`` and
remembered across runs.

To bypass the prompt:

- CLI: ``python -m isaacteleop.cloudxr --accept-eula``.
- API: ``CloudXRLauncher(accept_eula=True)``.

For non-interactive environments (CI, containers, child processes
without a controlling TTY) ``accept_eula=True`` is required; the
interactive prompt will otherwise raise :class:`RuntimeError` via
``SystemExit`` on EOF.

See :doc:`license` for the full license text and licensing notes.

Troubleshooting
---------------

Runtime did not start within 30 s
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`CloudXRLauncher` raises ``RuntimeError: CloudXR runtime failed
to start within 30s``.  The exception message already includes a tail
of ``logs/runtime_stderr.log`` and the newest
``logs/cxr_server.*.log``; those are the first files to inspect.

Common causes:

- No compatible GPU / Vulkan loader available in the subprocess.
  Check ``runtime_stderr.log`` for Vulkan errors.
- ``LD_LIBRARY_PATH`` pulled in an incompatible OpenSSL (host apps like
  Isaac Sim sometimes do this).  The launcher loads ``libcloudxr.so``
  with ``RTLD_DEEPBIND`` to mitigate; confirm your environment hasn't
  disabled that.
- The previous runtime is still alive holding ``run/ipc_cloudxr``.
  The launcher tries ``fuser -k -TERM`` automatically; if ``fuser`` is
  not on ``PATH``, install ``psmisc`` or terminate the stale process
  manually.

EULA prompt hangs in a non-interactive context
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If no ``eula_accepted`` marker exists and stdin is not a TTY, the
launcher raises ``RuntimeError: CloudXR EULA was not accepted``.  Pass
``accept_eula=True`` (or ``--accept-eula``) for unattended runs.

Runtime dies mid-session
^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`health_check` will raise
``RuntimeError: CloudXR runtime process exited unexpectedly``.  The
runtime's exit code is not surfaced directly; read
``logs/cxr_server.<ts>.log`` from the aborted run for the cause.  Call
:meth:`stop` to clean up the surviving WSS thread before constructing
a new launcher.

WSS proxy thread stopped unexpectedly
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`health_check` reports ``RuntimeError: CloudXR WSS proxy thread
stopped unexpectedly``.  The thread logs its traceback via the
``isaacteleop.cloudxr.launcher`` logger and writes request-level
details to ``logs/wss.<ts>.log``.  Enable Python logging at ``INFO`` or
``DEBUG`` on that logger to capture the startup exception.

See also
--------

- :doc:`../getting_started/quick_start` — end-to-end first-run tutorial.
- :doc:`oob_teleop_control` — OOB control hub sharing the WSS TLS port.
- :doc:`license` — EULA text and Isaac Teleop / CloudXR licensing.
