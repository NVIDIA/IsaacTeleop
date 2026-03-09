.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Ecosystem
=========

Supported Input Devices
------------------------

Isaac Teleop supports multiple XR headsets and tracking peripherals. Each device provides different
input modes, which determine which retargeters and control schemes are available.

.. list-table:: XR Headsets and Tracking Peripherals
   :header-rows: 1
   :widths: 20 25 25 30

   * - Device
     - Input Modes
     - Client / Connection
     - Notes
   * - Apple Vision Pro
     - Hand tracking (26 joints), spatial controllers
     - `Isaac XR Teleop Sample Client`_ (visionOS app)
     - Build from source; see :doc:`../getting_started/build_from_source`
   * - Meta Quest 3
     - Motion controllers (triggers, thumbsticks, squeeze), hand tracking
     - `Isaac Teleop Web Client`_ (browser)
     - See :ref:`Connect Quest and Pico <connect-quest-pico>`
   * - Pico 4 Ultra
     - Motion controllers, hand tracking
     - `Isaac Teleop Web Client`_ (browser)
     - Requires Pico OS 15.4.4U+
   * - `Pico Motion Tracker`_
     - Full body tracking
     - `Isaac Teleop Web Client`_ (browser)
     - Requires Pico OS 15.4.4U+

In addition to the fully integrated XR headsets, Isaac Teleop also supports standalone input
devices. Those devices are typically directly connected to the workstation where the Isaac Teleop
session is running via USB or Bluetooth. See :ref:`device-interface-device-plugin` for more details.

.. list-table:: Standalone Input Devices
   :header-rows: 1
   :widths: 20 25 25

   * - Device
     - Input Modes
     - Client / Connection
   * - Manus Gloves
     - High-fidelity finger tracking (Manus SDK)
     - `Manus Gloves Plugin`_ (CLI tool)
   * - Logitech Rudder Pedals
     - 3-axis foot pedal
     - `Generic 3-axis Pedal Plugin`_ (CLI tool)
   * - OAK-D Camera
     - Offline data recording
     - `OAK-D Camera Plugin`_ (CLI tool)

Planned Input Device Support
-----------------------------

The following input devices are planned for support in the future:

.. list-table:: Planned Input Devices
   :header-rows: 1
   :widths: 20 25 25 15

   * - Device
     - Input Modes
     - Client / Connection
     - ETA
   * - Keyboard and Mouse
     - Keyboard and mouse input
     - CLI tool
     - Q2 2026

..
   References
.. _`Pico Motion Tracker`: https://www.picoxr.com/global/products/pico-motion-tracker
.. _`Isaac XR Teleop Sample Client`: https://github.com/isaac-sim/isaac-xr-teleop-sample-client-apple
.. _`Isaac Teleop Web Client`: https://nvidia.github.io/IsaacTeleop/client
.. _`Manus Gloves Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/manus
.. _`Generic 3-axis Pedal Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/generic_3axis_pedal
.. _`OAK-D Camera Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/oak
