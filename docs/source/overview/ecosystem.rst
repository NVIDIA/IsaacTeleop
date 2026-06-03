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
   * - `Apple Vision Pro`_
     - Hand tracking (26 joints), spatial controllers
     - `Isaac XR Teleop Sample Client`_ (visionOS app)
     - Build from source; see :ref:`Connect Apple Vision Pro <connect-apple-vision-pro>`
   * - `Meta Quest 2/3/3S`_
     - Motion controllers (triggers, thumbsticks, squeeze), hand tracking
     - `Isaac Teleop Web Client`_ (browser)
     - See :ref:`Connect Quest and Pico <connect-quest-pico>`
   * - `Pico 4 Ultra`_
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
   * - `Manus Gloves`_
     - High-fidelity finger tracking (Manus SDK)
     - `Manus Gloves Plugin`_ (CLI tool)
   * - `Logitech Rudder Pedals`_
     - 3-axis foot pedal
     - `Generic 3-axis Pedal Plugin`_ (CLI tool)
   * - `OAK-D Camera`_
     - Offline data recording
     - `OAK-D Camera Plugin`_ (CLI tool)

Planned Input Device Support
-----------------------------

The following input devices and device categories are planned for support in the future:

.. list-table:: Planned Input Devices
   :header-rows: 1
   :widths: 20 25 25 25

   * - Device
     - Input Modes
     - Client / Connection
     - Status
   * - JoyLo
     - Master Manipulators
     - CLI tool with USB connection
     - Planning, see `#272 <https://github.com/NVIDIA/IsaacTeleop/issues/272>`_
   * - Gello
     - Master Manipulators
     - CLI tool with USB connection
     - Planning, see `#273 <https://github.com/NVIDIA/IsaacTeleop/issues/273>`_
   * - `Haply`_
     - Master Manipulators
     - CLI tool with USB connection
     - Planning, see `#274 <https://github.com/NVIDIA/IsaacTeleop/issues/274>`_
   * - SO-101
     - Master Manipulators
     - CLI tool with USB connection
     - Planning, see `#275 <https://github.com/NVIDIA/IsaacTeleop/issues/275>`_
   * - `3D Space Mouse`_
     - HID input
     - CLI tool with USB connection
     - Planning, see `#276 <https://github.com/NVIDIA/IsaacTeleop/issues/276>`_
   * - Gamepad
     - HID input
     - CLI tool with USB/Bluetooth connection
     - Planning, see `#277 <https://github.com/NVIDIA/IsaacTeleop/issues/277>`_
   * - Keyboard
     - HID input
     - CLI tool with USB/Bluetooth connection
     - Planning, see `#278 <https://github.com/NVIDIA/IsaacTeleop/issues/278>`_

Targeted Robotics Embodiments
-----------------------------

- Retarget the standardized device outputs to different embodiments.
- `Reference retargeter implementations <https://github.com/NVIDIA/IsaacTeleop/tree/main/src/retargeters/>`_,
  including popular embodiments such as Unitree G1.
- `Retargeter tuning UI <https://github.com/NVIDIA/IsaacTeleop/tree/main/src/core/retargeting_engine_ui/python>`_ to facilitate
  live retargeter tuning.

Device Acquisition
------------------

For inquiries about acquiring supported or planned devices, please contact the manufacturers
directly. Each device name in the tables above links to the corresponding manufacturer page.

.. list-table:: Manufacturer Contacts
   :header-rows: 1
   :widths: 20 35 45

   * - Manufacturer
     - Devices
     - Acquisition Contact
   * - `Apple`_
     - Apple Vision Pro
     -
   * - `Meta`_
     - Meta Quest 2/3/3S
     -
   * - `Pico`_ (ByteDance)
     - Pico 4 Ultra, Pico Motion Tracker
     - | Veronica Li
       | Email: Veronica.li@bytedance.com
       | Mobile: +1 (909) 569-2774
   * - `Manus`_
     - Manus Gloves
     -
   * - `Logitech`_
     - Logitech Rudder Pedals
     -
   * - `Luxonis`_
     - OAK-D Camera
     -
   * - `Haply`_
     - Haply (planned)
     -
   * - `3Dconnexion`_
     - 3D Space Mouse (planned)
     -

..
   References

.. Manufacturer / vendor home pages
.. _Apple: https://www.apple.com/
.. _Meta: https://www.meta.com/
.. _Pico: https://www.picoxr.com/
.. _Manus: https://www.manus-meta.com/
.. _Logitech: https://www.logitechg.com/
.. _Luxonis: https://www.luxonis.com/
.. _Haply: https://www.haply.co/
.. _`3Dconnexion`: https://3dconnexion.com/

.. Device product pages (used as link targets for device names in the tables above)
.. _`Apple Vision Pro`: https://www.apple.com/apple-vision-pro/
.. _`Meta Quest 2/3/3S`: https://www.meta.com/quest/
.. _`Pico 4 Ultra`: https://www.picoxr.com/products/pico4-ultra
.. _`Pico Motion Tracker`: https://www.picoxr.com/global/products/pico-motion-tracker
.. _`Manus Gloves`: https://www.manus-meta.com/products/quantum-metagloves
.. _`Logitech Rudder Pedals`: https://www.logitechg.com/en-us/products/flight/flight-simulator-rudder-pedals.html
.. _`OAK-D Camera`: https://shop.luxonis.com/products/oak-d
.. _`3D Space Mouse`: https://3dconnexion.com/us/spacemouse/

.. Other references
.. _`Isaac XR Teleop Sample Client`: https://github.com/isaac-sim/isaac-xr-teleop-sample-client-apple
.. _`Manus Gloves Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/manus
.. _`Generic 3-axis Pedal Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/generic_3axis_pedal
.. _`OAK-D Camera Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/oak
