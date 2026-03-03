Device Interface
================

Supported Devices
-----------------

Isaac Teleop supports multiple XR headsets and tracking peripherals. Each device provides different
input modes, which determine which retargeters and control schemes are available.

.. list-table::
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
     - Requires Pico OS 15.4.4U+; must use HTTPS mode
   * - Manus Gloves
     - High-fidelity finger tracking (Manus SDK)
     - `Manus Gloves Plugin`_ (CLI tool)
     - See :doc:`../getting_started/build_from_source` for installation instructions.
   * - Logitech Rudder Pedals
     - 3-axis foot pedal
     - `Generic 3-axis Pedal Plugin`_ (CLI tool)
     - See :doc:`../getting_started/build_from_source` for installation instructions.


Add a New Device
----------------

There are two levels of device integration:

**Isaac Teleop plugin (C++ level)**
   For new hardware that requires a custom driver or SDK. Plugins push data via OpenXR tensor
   collections. Existing plugins include Manus gloves, OAK-D camera, controller synthetic hands,
   and foot pedals. After creating the plugin, update the retargeting pipeline config to consume
   data from the new plugin's source node.

   See the `Plugins directory <https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/>`_ for examples.

..
   References
.. _`Isaac XR Teleop Sample Client`: https://github.com/isaac-sim/isaac-xr-teleop-sample-client-apple
.. _`Isaac Teleop Web Client`: https://nvidia.github.io/IsaacTeleop/client
.. _`Manus Gloves Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/manus
.. _`Generic 3-axis Pedal Plugin`: https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/generic_3axis_pedal
