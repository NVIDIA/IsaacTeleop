.. SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

MANUS Gloves
============

A Linux-only plugin for integrating `MANUS <https://www.manus-meta.com/>`_ gloves
into the Isaac Teleop framework. It provides full hand-joint tracking via the
Manus SDK and injects the resulting poses into the OpenXR hand-tracking layer so
any downstream retargeter can consume them transparently.

.. contents:: On this page
   :local:
   :depth: 2

Components
----------

- **Core library** (``manus_plugin_core``) — wraps the Manus SDK
  (``libIsaacTeleopPluginsManus.so``) and exposes per-joint tracking data.
- **Plugin executable** (``manus_hand_plugin``) — the main plugin binary that
  integrates with the Teleop system via CloudXR / OpenXR.
- **CLI tool** (``manus_hand_tracker_printer``) — a standalone diagnostic tool
  that prints tracked joint data to the terminal and opens a real-time
  **MANUS Data Visualizer** window showing the hand skeleton from two orthographic
  views per hand.

Prerequisites
-------------

- **Linux** — x86_64 (tested on Ubuntu 22.04 / 24.04).
- **Manus SDK** for Linux — downloaded automatically by the install script.
- **System dependencies** — the install script installs required packages automatically.

Installation
------------

MANUS access has two halves: **device permissions** (kernel/udev, lives on the
host) and **SDK + plugin build** (lives wherever you build, typically a
container). The two scripts below split along that line.

Step 1: grant the host access to the Manus dongle (one-time)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run this **on the host machine**, not inside a container. udev rules are
processed by ``systemd-udevd``, which does not run inside Docker — so
installing rules from a container has no effect.

.. code-block:: bash

   cd src/plugins/manus
   ./install_udev_rules.sh
   # then unplug + replug the Manus dongle

If you're using the Isaac ROS dev container (``isaac_ros run_dev``), it
bind-mounts ``/dev/bus/usb`` from the host, so once the host has the rules
applied the container will see the dongle with the right permissions.

Step 2: build the SDK and plugin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run this **inside the build environment** (devcontainer or Isaac ROS container):

.. code-block:: bash

   cd src/plugins/manus
   ./install_manus.sh

The script will:

1. Install the required system packages for MANUS Core Integrated.
2. Download MANUS SDK v3.1.1.
3. Extract and place the SDK in the correct location.
4. Build the plugin and the diagnostic tool.

When run inside a container, ``install_manus.sh`` skips the udev step and
reminds you to run ``install_udev_rules.sh`` on the host.

Manual installation
~~~~~~~~~~~~~~~~~~~

If you prefer to install manually:

1. Download the MANUS Core SDK from
   `MANUS Downloads <https://docs.manus-meta.com/3.1.1/Resources/>`_.
2. Extract and place the ``ManusSDK`` folder inside ``src/plugins/manus/``, or
   point CMake at a different path by setting ``MANUS_SDK_ROOT``.
3. Follow the
   `MANUS Getting Started guide for Linux <https://docs.manus-meta.com/3.1.1/Plugins/SDK/Linux/>`_
   to install the dependencies and configure device permissions.

Expected directory layout after placing the SDK:

.. code-block:: text

   src/plugins/manus/
     app/
       main.cpp
     core/
       manus_hand_tracking_plugin.cpp
     inc/
       core/
         manus_hand_tracking_plugin.hpp
     tools/
       manus_hand_tracker_printer.cpp
     ManusSDK/        <-- placed here
       include/
       lib/

Then build from the root:

.. code-block:: bash

   cd ../../..  # navigate to root
   cmake -S . -B build
   cmake --build build --target manus_hand_plugin manus_hand_tracker_printer -j
   cmake --install build --component manus

Running the Plugin
------------------

1. Start the CloudXR runtime and load its environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The MANUS plugin connects to the Teleop session through the CloudXR / OpenXR
runtime, so the runtime must be running and its environment sourced in the
shell that launches the plugin.

In one terminal, start the CloudXR runtime (keep it running for the duration
of the session):

.. code-block:: bash

   python -m isaacteleop.cloudxr

In the terminal you will use to run the plugin, source the environment file
that the runtime writes on startup. This points the OpenXR loader at CloudXR:

.. code-block:: bash

   source ~/.cloudxr/run/cloudxr.env

See :ref:`run-cloudxr-server` and :ref:`whitelist-firewall-ports`
in the Quick Start for the full CloudXR runtime setup, including EULA
acceptance and firewall configuration.

2. Verify with the CLI tool
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Verify that the gloves are working using the CLI tool:

.. code-block:: bash

   ./build/bin/manus_hand_tracker_printer

The tool prints joint positions to the terminal and opens a **MANUS Data
Visualizer** window showing a top-down and side view of each hand.

3. Run the plugin
~~~~~~~~~~~~~~~~~~

The plugin is installed to the ``install`` directory. Ensure the CLI tool is
not running when you launch the plugin — only one process can hold the Manus
SDK connection at a time.

.. code-block:: bash

   ./install/plugins/manus/manus_hand_plugin

Wrist Positioning — Controllers vs Optical Hand Tracking
---------------------------------------------------------

Two sources are available for positioning the MANUS gloves in 3D space:

- **Controller adapters** — attach Quest 3 controllers to the MANUS Universal
  Mount on the back of the glove. The controller pose drives wrist placement.
- **Optical hand tracking** — use the HMD's built-in optical hand tracking to
  position the hands. No physical controller adapter required.

The plugin selects the source automatically at runtime: optical hand tracking is
preferred when ``XR_MNDX_xdev_space`` is supported and the runtime reports an
actively tracked wrist pose; otherwise it falls back to the controller pose.

.. note::

   When using controller adapters it is advisable to disable the HMD's automatic
   hand-tracking–to–controller switching to avoid unexpected source changes
   mid-session.

Troubleshooting
---------------

.. list-table::
   :widths: 40 60
   :header-rows: 1

   * - Symptom
     - Resolution
   * - SDK download fails
     - Check your internet connection and re-run the install script.
   * - Manus SDK not found at build time
     - With manual installation, ensure ``ManusSDK`` is inside
       ``src/plugins/manus/`` or set ``MANUS_SDK_ROOT`` to your installation path.
   * - Manus SDK not found at runtime
     - The build configures RPATH automatically. If you moved the SDK after
       building, set ``LD_LIBRARY_PATH`` to its ``lib/`` directory.
   * - No data received
     - Ensure MANUS Core is running and the gloves are connected and calibrated.
   * - CloudXR runtime errors
     - Make sure the CloudXR runtime is running (``python -m isaacteleop.cloudxr``)
       and that ``~/.cloudxr/run/cloudxr.env`` has been sourced in the same
       terminal as the plugin.
   * - Permission denied for USB devices
     - udev rules must be installed on the host. Run ``./install_udev_rules.sh``
       from the host (not inside a container), then unplug and replug the
       MANUS dongle. Verify on the host with ``ls -l /dev/hidraw*`` — entries for the
       dongle should be mode ``0666``.
   * - ``udevadm control --reload-rules`` fails with "No such file or directory"
     - You're inside a container. ``systemd-udevd`` doesn't run in containers,
       so this command can never succeed there. Run ``install_udev_rules.sh``
       on the host instead.
   * - Dongle not visible inside the Isaac ROS container (``lsusb`` doesn't
       show vendor ``3325``)
     - The container needs ``/dev/bus/usb`` bind-mounted from the host. The
       Isaac ROS dev container does this automatically; for a custom
       ``docker run``, add ``-v /dev/bus/usb:/dev/bus/usb`` (or
       ``--device=/dev/hidraw<N>`` for a specific device).

License
-------

Source files are covered by their stated licenses (Apache-2.0). The Manus SDK is
proprietary to MANUS and is subject to its own license; it is **not** redistributed
by this project.
