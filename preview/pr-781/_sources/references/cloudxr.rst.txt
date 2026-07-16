.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

.. _dedicated-cloudxr-runtime:

Dedicated CloudXR Runtime
=========================

The teleop examples auto-launch the CloudXR runtime and its WSS proxy through
``CloudXRLauncher`` when they connect, so for the common workflow you never
start the runtime yourself (see :ref:`run-cloudxr-server` in the quick start).
Sometimes, though, you want the runtime running **standalone in its own
terminal**:

- keep the runtime — and the headset connection — alive while you restart your
  teleop application repeatedly during development,
- point OpenXR applications that do not embed ``CloudXRLauncher`` at CloudXR,
- use launch modes that only the standalone launcher exposes, such as serving
  the web client locally (``--host-client``) or the out-of-band automation
  flags (``--setup-oob``, ``--usb-local``).

This page describes that dedicated workflow.

.. contents:: Sections
   :local:
   :depth: 1
   :backlinks: none

Start the runtime
-----------------

With the ``isaacteleop`` package installed (including the ``cloudxr`` extra,
see :ref:`install-isaacteleop-pip-package`), start the CloudXR runtime and WSS
proxy. The first run downloads the CloudXR Web Client SDK and asks you to
review and accept the EULA:

.. code-block:: bash

   python -m isaacteleop.cloudxr

To bypass the interactive EULA prompt (e.g. for CI or headless runs), pass the
flag:

.. code-block:: bash

   python -m isaacteleop.cloudxr --accept-eula

You should see output similar to:

.. figure:: ../_static/cloudxr-run-output.png
   :alt: CloudXR run output
   :align: center

   **Figure:** CloudXR run output

.. important::

   Keep this terminal open — CloudXR must stay running for the duration of the
   session (``Ctrl+C`` terminates it). Open a **new terminal** for the
   remaining steps.

   Also take note of the ``source ~/.cloudxr/run/cloudxr.env`` path mentioned
   in the output. You will need to source it in
   :ref:`load-cloudxr-environment-variables`.

Optional launch modes
---------------------

The launcher supports optional flags that can be combined to control how the
headset connects and how the web client is delivered.

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Command
     - What it does
   * - ``python -m isaacteleop.cloudxr``
     - Plain: headset navigates to GitHub Pages URL over WiFi.
   * - ``python -m isaacteleop.cloudxr --host-client``
     - Serves the web client at ``https://<ip>:48322/client/`` via the WSS
       proxy. No separate port, no USB or TURN relay required. Useful when
       GitHub Pages is unreachable.
   * - ``python -m isaacteleop.cloudxr --setup-oob``
     - OOB hub + CDP automation: opens the browser on the headset and
       auto-clicks CONNECT over USB adb. Client URL is GitHub Pages.
   * - ``python -m isaacteleop.cloudxr --setup-oob --host-client``
     - OOB hub + CDP with client at ``/client/`` on the WSS proxy
       (air-gapped / proxy use).
   * - ``python -m isaacteleop.cloudxr --setup-oob --usb-local``
     - All traffic over USB: adb-reverse + coturn TURN relay + loopback
       HTTPS. Requires ``coturn`` and a WiFi-associated headset.

``--usb-local`` requires ``--setup-oob``. See
:doc:`/references/oob_teleop_control` for full OOB documentation.

.. _load-cloudxr-environment-variables:

Load CloudXR environment variables
----------------------------------

On every start the runtime writes its resolved environment to
``~/.cloudxr/run/cloudxr.env`` (the exact path is printed in the startup
output). Sourcing it points the OpenXR loader at CloudXR — it sets
``XR_RUNTIME_JSON`` along with the ``NV_CXR_*`` variables — so any OpenXR
application started from that terminal connects to the dedicated runtime.

Open a new terminal and source the setup script:

.. code-block:: bash

   source ~/.cloudxr/run/cloudxr.env

.. important::

   Make sure to run the rest of the commands in the same terminal. If you have
   to open a new terminal, source the CloudXR environment variables again.

Run teleop examples against the dedicated runtime
-------------------------------------------------

The teleop examples under ``examples/teleop/python/`` launch their own runtime
by default. When a dedicated runtime is already running, source the env file
(previous section) and pass ``--no-launch-cloudxr-runtime`` so the example
uses the running runtime instead of starting another one:

.. code-block:: bash

   source ~/.cloudxr/run/cloudxr.env
   python examples/teleop/python/gripper_retargeting_example_simple.py \
         --no-launch-cloudxr-runtime

Configuration
-------------

The standalone launcher accepts the same configuration flags as the embedded
one:

- ``--cloudxr-env-config <PATH>`` — a ``KEY=value`` env file of CloudXR
  runtime overrides, e.g. ``NV_DEVICE_PROFILE=auto-native``. See
  :ref:`run-cloudxr-server` in the quick start for the list of supported
  environment variables.
- ``--cloudxr-install-dir <PATH>`` — CloudXR install directory
  (default: ``~/.cloudxr``).

To inspect the active settings after startup:

.. code-block:: bash

   cat ~/.cloudxr/run/cloudxr.env
