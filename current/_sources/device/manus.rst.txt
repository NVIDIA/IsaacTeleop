..
   SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
   SPDX-License-Identifier: Apache-2.0

Manus Gloves
============

A Linux-only plugin for integrating `Manus <https://www.manus-meta.com/>`_ gloves
into the Isaac Teleop framework. It provides full hand-joint tracking via the
Manus SDK and injects the resulting poses into the OpenXR hand-tracking layer so
any downstream retargeter can consume them transparently.

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

Automated (recommended)
~~~~~~~~~~~~~~~~~~~~~~~~

The install script handles SDK download, dependency installation, and building:

.. code-block:: bash

   cd src/plugins/manus
   ./install_manus.sh

The script will:

1. Install the required system packages for MANUS Core Integrated.
2. Download MANUS SDK v3.1.1.
3. Extract and place the SDK in the correct location.
4. Build the plugin and the diagnostic tool

Manual
~~~~~~

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

1. Set up the CloudXR environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Source the CloudXR environment and start the runtime before running the plugin:

.. code-block:: bash

   export NV_CXR_RUNTIME_DIR=~/.cloudxr/run
   export XR_RUNTIME_JSON=~/.cloudxr/openxr_cloudxr.json

2. Verify with the CLI tool
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Verify that the gloves are working using the CLI tool:

.. code-block:: bash

   ./build/bin/manus_hand_tracker_printer

The tool prints joint positions to the terminal and opens a **MANUS Data
Visualizer** window showing a top-down and side view of each hand.

3. Run the plugin
~~~~~~~~~~~~~~~~~~

The plugin is installed to the `install` directory, please ensure the CLI tool is not running when running the plugin.

.. code-block:: bash

   ./install/plugins/manus/manus_hand_plugin

Wrist Positioning — Controllers vs Optical Hand Tracking
---------------------------------------------------------

Two sources are available for positioning the Manus gloves in 3D space:

- **Controller adapters** — attach Quest 3 controllers to the Manus Universal
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
     - Ensure Manus Core is running and the gloves are connected and calibrated.
   * - CloudXR runtime errors
     - Make sure ``scripts/setup_cloudxr_env.sh`` has been sourced before running.
   * - Permission denied for USB devices
     - The install script configures udev rules. If the rules were not reloaded,
       run:

       .. code-block:: bash

          sudo udevadm control --reload-rules
          sudo udevadm trigger

       Then reconnect your Manus devices.

License
-------

Source files are covered by their stated licenses (Apache-2.0). The Manus SDK is
proprietary to Manus and is subject to its own license; it is **not** redistributed
by this project.
