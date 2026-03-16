System Requirements
===================

Isaac Teleop can be used for teleoperation of robots, data collection, and human-centric data
collection. The hardware & software requirements are different for each use case.

Direct Teleoperation to Robots
------------------------------

.. figure:: ../_static/hardware-req-01.svg
    :width: 75%
    :alt: Hardware requirements for direct teleoperation to real robots
    :class: no-image-zoom

For the bare minimum use case, you can use an XR headset to teleoperate a robot directly. No extra
hardware is required. NVIDIA CloudXR server and Isaac Teleop can be **run directly on the robot**.

.. list-table::
    :widths: 30 70
    :header-rows: 1

    * - Component
      - Requirement
    * - XR Device
      - | Pico 4 Ultra Enterprise (Recommended) [#cloudxr-js-req]_
        | Pico 4 Ultra [#cloudxr-js-req]_
        | Apple Vision Pro (with PSVR2 controllers) [#cloudxr-js-req]_
        | Meta Quest 3
    * - CPU / GPU (Robot)
      - NVIDIA Jetson Thor [#jetson-orin]_
    * - OS (Robot)
      - Ubuntu 22.04 or 24.04 (ARM64)
    * - Python
      - 3.10 / 3.11 / 3.12
    * - CUDA
      - 12.8 or newer
    * - NVIDIA Driver
      - 580.95.05 or newer


Teleoperation to Robots with Extra Input Devices
------------------------------------------------

.. figure:: ../_static/hardware-req-02.svg
    :width: 75%
    :alt: Hardware requirements for teleoperation with extra input devices
    :class: no-image-zoom

When using extra input devices (such as Manus Gloves, Logitech Rudder Pedals, OAK-D Camera, etc.),
Isaac Teleop needs to be **run on a laptop or workstation**, that is connected to the robot via
network.  The minimum requirements for the laptop/workstation are:

.. list-table::
    :widths: 30 70
    :header-rows: 1

    * - Component
      - Requirement
    * - CPU / GPU
      - x86_64 [#jetson-nano]_, NVIDIA GPU required
    * - OS
      - Ubuntu 22.04 or 24.04
    * - Python
      - 3.10 / 3.11 / 3.12
    * - CUDA
      - 12.8 or newer
    * - NVIDIA Driver
      - 580.95.05 or newer

Teleoperation with Isaac Sim and Isaac Lab
-------------------------------------------

.. figure:: ../_static/hardware-req-03.svg
    :width: 75%
    :alt: Hardware requirements for teleoperation with Isaac Sim and Isaac Lab
    :class: no-image-zoom

For running simulation with Isaac Sim and Isaac Lab with RTX rendering, the CloudXR server and
Isaac Teleop sessions need to be **run on the same workstation with Isaac Sim and Isaac Lab**. The
workstation's system requirements are driven by Isaac Sim and Isaac Lab [#isaacsim-req]_.

The recommended workstation configuration for Sim-based Teleop is:

.. list-table::
    :widths: 30 70
    :header-rows: 1

    * - Component
      - Requirement
    * - CPU
      - AMD Ryzen Threadripper 7960x
    * - GPU
      - 1x RTX 6000 Pro (Blackwell) or 2x RTX 6000 (Ada)
    * - OS
      - Ubuntu 22.04 [#isaaclab-req]_
    * - Python
      - 3.12 [#isaaclab-req]_
    * - CUDA
      - 12.8 or newer
    * - NVIDIA Driver
      - 580.95.05 or newer

If you are only using XR headsets for teleoperation, you can host the workstation in the cloud.
See `Isaac Lab Cloud Deployment <https://isaac-sim.github.io/IsaacLab/main/source/deployment/index.html>`_
for more details.

Human-centric Data Collection
------------------------------

Isaac Teleop can also be used for human-centric data collection without a robot or simulator in the
loop. In this case, Isaac Teleop needs to be **run on a laptop or workstation**, that is connected
to device peripherals. The minimum requirements for the laptop/workstation are:

.. figure:: ../_static/hardware-req-04.svg
    :width: 75%
    :alt: Hardware requirements for human-centric data collection
    :class: no-image-zoom

.. list-table::
    :widths: 30 70
    :header-rows: 1

    * - Component
      - Requirement
    * - CPU / GPU
      - x86_64 [#jetson-nano]_, NVIDIA GPU required
    * - OS
      - Ubuntu 22.04 or 24.04
    * - Python
      - 3.10 / 3.11 / 3.12
    * - CUDA
      - 12.8 or newer
    * - NVIDIA Driver
      - 580.95.05 or newer

.. rubric:: Footnotes

.. [#cloudxr-js-req] Please refer to `CloudXR.js Requirements <https://docs.nvidia.com/cloudxr-sdk/latest/requirement/cloudxrjs_req.html>`_
   for more details.

.. [#jetson-orin] Jetson Orin support is being considered. See
   `#269 <https://github.com/NVIDIA/IsaacTeleop/issues/269>`_
   for more details. Please up-vote and/or comment on the issue if you are interested in this feature.

.. [#jetson-nano] Jetson Nano support is being considered. See
   `#271 <https://github.com/NVIDIA/IsaacTeleop/issues/271>`_
   for more details. Please up-vote and/or comment on the issue if you are interested in this feature.

.. [#isaacsim-req] Please refer to `Isaac Sim System Requirements <https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html>`_
   for more details.

.. [#isaaclab-req] Please refer to `Isaac Lab System Requirements <https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/index.html#general-requirements>`_
   for more details.
