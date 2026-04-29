Device Interface
================

.. _device-interface-device-plugin:

Isaac Teleop device plugin (C++ level)
--------------------------------------

For new hardware that requires a custom driver or SDK. Plugins push data via OpenXR tensor
collections. Existing plugins include Manus gloves, OAK-D camera, controller synthetic hands,
and foot pedals. After creating the plugin, update the retargeting pipeline config to consume
data from the new plugin's source node.

See the `Plugins directory <https://github.com/NVIDIA/IsaacTeleop/tree/main/src/plugins/>`_ for examples.

.. toctree::
   :maxdepth: 2
   :caption: Device

   trackers
   add_device
   body_tracking
