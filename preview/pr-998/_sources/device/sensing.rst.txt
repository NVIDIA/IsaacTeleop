.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

SENSING GMSL Camera Plugin
==========================

C++ plugin that captures from SENSING GMSL2 cameras through **SIPL** on a
Jetson AGX Orin, and either encodes H.264 on the Jetson's V4L2 engine or hands
frames to another process as CUDA device memory. Source and plugin README:
:code-file:`src/plugins/sensing/README.md`.

.. contents:: On this page
   :local:
   :depth: 2

Supported hardware
------------------

This plugin is developed and verified against exactly one configuration:

.. list-table::
   :widths: 30 70
   :header-rows: 0

   * - Host
     - NVIDIA Jetson AGX Orin (``p3737-0000 + p3701-0005``, 64 GB)
   * - Software
     - JetPack 7.2.1 / L4T R39.2.1
   * - Carrier
     - SENSING **SG8A-AGON-G2Y-A1** (GMSL2)
   * - Cameras
     - Two Astra **SHW5G** (VB1940), 2560×1984 @ 60 fps, RAW10 → ISP
   * - Platform config
     - ``SHW5G_2`` on CN1 CAM2/CAM3, link masks ``0x0000 0x1100``
   * - Device tree
     - ``Jetson Sensing SG8A-AGON-G2Y-A1 SIPL GMSL2x8``

The carrier also takes S56C and SHF3L modules, and the vendor package ships
``S56C_1_SHF3L_2`` and ``SHF3L_2_SHW5G_2`` configs for them. Those remain
*addressable* — the config name and JSON path are arguments — but nothing is
built or tested for them. They would also need an ICP passthrough path, since
the SHF3L modules are YUV422 sensors that bypass the ISP entirely.

Drivers come from the vendor SIPL package, which supplies userspace device
drivers (``libnvuddf_*.so``), a device-tree overlay, and NITO ISP tuning files.
The scripts below wrap it; they do not replace it.

What SIPL changes
-----------------

If you know the previous Argus-based rig, almost every operational assumption
moved:

.. list-table::
   :widths: 22 39 39
   :header-rows: 1

   * -
     - Argus (SG10A)
     - SIPL (SG8A)
   * - Sensor drivers
     - kernel ``.ko``, loaded every boot
     - userspace ``.so`` in ``/usr/lib/nvsipl_drv``
   * - Device nodes
     - ``/dev/video0..9``
     - none
   * - Arbitration
     - ``nvargus-daemon``, multi-client
     - in-process, **exclusive**
   * - Per-boot step
     - ``load_modules.sh`` + systemd unit
     - none
   * - Frame sync
     - PWM trigger + J19 strap
     - deserializer ``fsyncMode: osc_manual``
   * - Geometry
     - ``--width``/``--height``/``--sensor-mode``
     - read from the platform config
   * - Privilege
     - container user + ``/tmp/argus_socket``
     - container user + two groups

.. warning::

   SIPL takes **exclusive** ownership of the hardware. ``nvsipl_camera`` and
   ``camera_plugin_sensing`` cannot run at the same time; stop one before
   starting the other. There is no daemon to arbitrate between them.

Setup
-----

Bring-up is two-sided and neither half can do the other's job: installing the
vendor drivers and selecting the overlay only happen on the host, while device
access and the build SDKs only matter inside the container.

.. code-block:: bash

   src/plugins/sensing/setup.sh      # auto-detects host vs container
   src/plugins/sensing/verify.sh     # read-only report, runs anywhere

Host
~~~~

.. code-block:: bash

   src/plugins/sensing/setup_host.sh --install-drivers   # first time only

Then select the overlay and reboot:

.. code-block:: bash

   sudo /opt/nvidia/jetson-io/jetson-io.py
   # Configure Jetson AGX CSI Connector
   #   -> Configure for compatible hardware
   #   -> Jetson Sensing SG8A-AGON-G2Y-A1 SIPL GMSL2x8
   sudo nvpmodel -m 0 && sudo jetson_clocks

.. note::

   There is **no per-boot step**. The vendor ``install.sh`` is copy-only, so
   once the overlay is selected the rig comes up on its own. The old
   ``sensing-load.sh`` and ``sensing-camera.service`` no longer exist.

Groups, not root
~~~~~~~~~~~~~~~~

SIPL needs no root, but it does need two supplementary groups beyond ``video``:

.. list-table::
   :widths: 35 15 50
   :header-rows: 1

   * - Node
     - Group
     - Why
   * - ``/dev/i2c-9``, ``/dev/i2c-10``
     - ``i2c``
     - the two MAX96712 deserializers
   * - ``/dev/gpiochip0``, ``/dev/gpiochip1``
     - ``gpio``
     - deserializer power enable

.. code-block:: bash

   sudo usermod -aG i2c,gpio $USER   # then log out and back in

Omit either and SIPL fails with exactly one line — ``Master SetPlatformConfig
(Camera HAL) failed. status: 10`` — which names neither the node nor the
permission. ``verify.sh`` diagnoses it properly.

Container
~~~~~~~~~

.. code-block:: bash

   src/plugins/sensing/setup_container.sh

Add the group ids to the container's ``runArgs`` (numeric, because the
container has no matching group *names*; the kernel checks numbers):

.. code-block:: json

   "--group-add", "114",
   "--group-add", "985"

The script also provisions both build SDKs, and both are public downloads
resolved from the version in ``/etc/nv_tegra_release``. The **Jetson Multimedia
API** comes from the apt pool; the **SIPL API** is a tarball published
alongside the L4T release, fetched by URL. To install that one by hand instead:

.. code-block:: bash

   sudo tar xf Jetson_SIPL_API_R39.2.1_aarch64.tbz2 -C /usr/src/

Building and running
--------------------

.. code-block:: bash

   cmake -B build -DBUILD_PLUGIN_SENSING=ON
   cmake --build build --target camera_plugin_sensing

The platform config is vendored at ``src/plugins/sensing/configs/shw5g.json``
and resolved relative to the executable, so the plugin runs without the vendor
package on disk; ``--platform-config=PATH`` points it at a newer vendor drop.

Start by asking the platform config what exists. This needs no hardware — the
query API only parses the driver database and the JSON, so it works with the
cameras unplugged:

.. code-block:: bash

   ./build/src/plugins/sensing/app/camera_plugin_sensing --list-sensors

.. code-block:: text

   SHW5G_2: 2 sensor(s)
     sensor=0  SHW5G  2560x1984 @ 60 fps
     sensor=1  SHW5G  2560x1984 @ 60 fps

.. warning::

   ``sensor=N`` is the **SIPL pipeline index**, and for ``SHW5G_2`` it is not
   the number the JSON appears to name. The GMSL link indices, the CSI virtual
   channels and the JSON's ``sensorInfo.id`` are all **2 and 3**; the pipeline
   indices are **0 and 1**. Always take the number from ``--list-sensors``.

   In the vendor's ``S56C_1_SHF3L_2`` config the two coincide, which is exactly
   why this is worth stating.

Geometry comes from the platform config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There is no ``--width``, ``--height``, ``--fps`` or ``--sensor-mode``. SIPL has
no runtime mode index; resolution and frame rate are properties of the virtual
channel in the platform config, and the plugin sizes its buffers from what the
query reports.

Encoding at 5 MP60
~~~~~~~~~~~~~~~~~~

Two sensors at 2560×1984 @ 60 is 4.9× the pixel rate the 1080p30 defaults were
chosen for, so the codec settings moved with it:

.. list-table::
   :widths: 25 20 55
   :header-rows: 1

   * - Setting
     - Value
     - Why
   * - level
     - **5.2**
     - 1,190,400 MB/s exceeds Level 5.1's 983,040 by 21%
   * - ``--bitrate``
     - 40 Mbps
     - 0.13 bits/pixel; 20 Mbps was 0.066
   * - ``--peak-bitrate``
     - 60 Mbps
     - VBR ceiling; pass ``0`` to select CBR

80 Mbps for the pair, about 36 GB/hour.

Live streaming with camera_viz
------------------------------

``ipc=<socket>`` serves a sensor's frames to another process as **CUDA device
memory** — RGBA8, no encode, no host round-trip — and
:code-file:`camera_viz <examples/camera_viz/README.md>` consumes it with
``type: cuda_ipc``. It is independent of ``output=``; an ``ipc``-only stream
never starts an encoder.

.. code-block:: bash

   # terminal 1 — producer
   ./build/src/plugins/sensing/app/camera_plugin_sensing \
       --add-stream=sensor=0,ipc=/tmp/sensing0.sock \
       --add-stream=sensor=1,ipc=/tmp/sensing1.sock

   # terminal 2 — viewer
   cd examples/camera_viz
   ./camera_viz.sh setup                                     # one-time
   ./camera_viz.sh run configs/cuda_ipc.yaml --mode window   # desktop window
   ./camera_viz.sh run configs/cuda_ipc.yaml                 # XR headset

:code-file:`configs/cuda_ipc.yaml <examples/camera_viz/configs/cuda_ipc.yaml>`
needs only the socket path and the frame size:

.. code-block:: yaml

   cameras:
     - name: left
       type: cuda_ipc
       socket: /tmp/sensing0.sock   # must match the producer's ipc= path
       width: 2560                  # must match what the producer serves
       height: 1984

Order does not matter — the source retries until the socket appears and survives
the producer restarting under it. ``width``/``height`` are checked during the
handshake and a mismatch is refused rather than rendered at the wrong stride.
**One consumer at a time**: the producer serves whoever connected most recently,
so a second viewer silently takes the feed from the first.

Pairing the two eyes
~~~~~~~~~~~~~~~~~~~~

Both sensors are driven from one deserializer fsync generator, and every frame
carries SIPL's ``frameCaptureTSC`` on a timebase shared across the whole rig.
It is recorded in the MCAP metadata as ``capture_tsc_ns``.

.. important::

   Pair on ``capture_tsc_ns``, not on the wrapper timestamps. The wrapper stamps
   are ``CLOCK_MONOTONIC`` taken after per-sensor conversion, so they carry each
   sensor's own queueing jitter; the TSC does not.

Testing without a camera
~~~~~~~~~~~~~~~~~~~~~~~~

``sensing_ipc_testsrc`` publishes an animated pattern over the same protocol. It
needs CUDA only — no SIPL, no encoder — so the viewer can be developed with
nothing attached:

.. code-block:: bash

   cmake --build build --target sensing_ipc_testsrc
   ./build/src/plugins/sensing/tools/sensing_ipc_testsrc --socket=/tmp/sensing0.sock \
       --width=2560 --height=1984 --fps=60

Each frame carries its 16-bit frame number as a binary bar across the top, so a
stale or torn frame is visible rather than merely suspected.

Troubleshooting
---------------

.. list-table::
   :widths: 45 55
   :header-rows: 1

   * - Symptom
     - Cause
   * - ``SetPlatformConfig (Camera HAL) failed. status: 10``
     - missing ``i2c`` or ``gpio`` group — run ``verify.sh``
   * - ``no modules left in '<config>' after applying the link masks``
     - ``--link-masks`` does not match the config
   * - ``cannot open NITO file .../SHW5G.nito``
     - vendor ``install.sh`` was never run on the host
   * - ``sensor=N is not a pipeline in '<config>'``
     - using the link index or the JSON id; run ``--list-sensors``
   * - capture hangs, no frames, no error
     - another SIPL client holds the hardware — stop ``nvsipl_camera``
   * - ``ISP0 reconciled to colour standard ...``
     - the ISP refused BT.601; see the note in ``sipl_camera.cpp``

The vendor smoke test is the reference for "is the rig itself alive":

.. code-block:: bash

   sudo nvsipl_camera -t $PKG/query/sg8a_agth_g2a/shw5g.json -c SHW5G_2 \
                      -m "0x0000 0x1100" --enable-camera-hal -s -Z

Expect ~60 fps per sensor with zero drops. Stop it before starting the plugin.
