.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Ecosystem
=========

Unified Stack for Sim & Real Teleoperation
-------------------------------------------

A single framework that works seamlessly across simulated and real-world robots, ensuring
streamlined device workflow and consistent data schemas.

.. list-table:: Robotics Stacks
   :header-rows: 1
   :widths: 15 50 20

   * - Stack
     - Description
     - Status
   * - ROS2
     - Widely adopted middleware for robot software integration and communication
     - Supported
   * - Isaac Sim
     - Simulation platform to develop, test, and train AI-powered robots
     - Supported (v6.0)
   * - Isaac Lab
     - Unified framework for robot learning designed to help train robot policies
     - Supported (v3.0)
   * - Isaac ROS
     - NVIDIA CUDA-accelerated toolkit for ROS2
     - Planned
   * - Isaac Arena
     - Isaac Lab extension for large-scale evaluation and resource orchestration
     - Planned (v0.2)

Supported Input Devices
------------------------

Isaac Teleop provides a standardized interface for teleoperation devices, removing the need for
custom device integrations and ongoing maintenance. It supports multiple XR headsets and tracking
peripherals. Each device provides different input modes, which determine which retargeters and
control schemes are available. Easily extend support for additional devices through a plugin system;
see :ref:`device-interface-device-plugin` for details.

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
     - Build from source; see :ref:`Connect Apple Vision Pro <connect-apple-vision-pro>`
   * - Meta Quest 3
     - Motion controllers (triggers, thumbsticks, squeeze), hand tracking
     - `Isaac Teleop Web Client`_ (browser)
     - See :ref:`Connect Quest and Pico <connect-quest-pico>`
   * - Pico 4 Ultra
     - Motion controllers, hand tracking
     - `Isaac Teleop Web Client`_ (browser)
     - Requires Pico OS 15.4.4U or newer
   * - `Pico Motion Tracker`_
     - Full body tracking
     - `Isaac Teleop Web Client`_ (browser)
     - | Requires Pico OS 15.4.4U or newer
       | Requires Pico Browser 4.0.40 or newer (Enterprise enabled)

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

The following input devices and device categories are planned for support in the future:

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
     - Planned
   * - Master Manipulators
     - Gello, Haply, JoyLo etc.
     - CLI tool
     - Planned
   * - Exoskeletons
     - TBA
     - TBA
     - TBA

Targeted Robotics Embodiments
-----------------------------

- Retarget the standardized device outputs to different embodiments.
- `Reference retargeter implementations <https://github.com/NVIDIA/IsaacTeleop/tree/main/src/retargeters/>`_,
  including popular embodiments such as Unitree G1.
- `Retargeter tuning UI <https://github.com/NVIDIA/IsaacTeleop/tree/main/src/core/retargeting_engine_ui/python>`_ to facilitate
  live retargeter tuning.

..
   References
.. _`Pico Motion Tracker`: https://www.picoxr.com/global/products/pico-motion-tracker
.. _`Isaac XR Teleop Sample Client`: https://github.com/isaac-sim/isaac-xr-teleop-sample-client-apple
.. _`Isaac Teleop Web Client`: https://nvidia.github.io/IsaacTeleop/client
.. _`Manus Gloves Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/manus
.. _`Generic 3-axis Pedal Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/generic_3axis_pedal
.. _`OAK-D Camera Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/oak
