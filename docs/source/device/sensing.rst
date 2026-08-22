.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

SENSING GMSL Camera Plugin
==========================

C++ plugin that captures from SENSING GMSL2 cameras through **libargus** on a
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
     - NVIDIA Jetson AGX Orin
   * - Software
     - JetPack 6.2 / L4T R36.4.3, kernel ``5.15.148-tegra``
   * - Carrier
     - SENSING **SG10A-AGON-G2M-A1** (GMSL2)
   * - Camera
     - Orbbec Astra **S56C**, 1920×1080 @ 30 fps, ``sensor_mode=0`` (its only mode)
   * - Device tree
     - ``Jetson Sensing SG10A_AGON_G2M_A1 S56Cx1 SHF3Lx6``

The carrier also takes up to six SHF3L/SHF3H modules. Those are **out of scope**
for this plugin — they are already ISP-processed on the module and stream YUV
over plain V4L2, so ``examples/camera_viz/configs/v4l2.yaml`` reads them
directly. The S56C emits 10-bit Bayer and *must* go through the ISP, which is
why it needs Argus.

Drivers come from the vendor package,
`nvidia-jetson-camera-drivers <https://github.com/SENSING-Technology/nvidia-jetson-camera-drivers>`_
(kernel ``Image``, sensor ``.ko`` files, ``.dtbo`` overlays, ISP tuning). The
scripts below wrap it; they do not replace it.

Setup
-----

Bring-up is two-sided and neither half can do the other's job: kernel modules,
the device-tree overlay and the POC/PWM register writes only exist on the host,
while the Argus client socket and the build headers only matter inside the
devcontainer.

.. code-block:: bash

   src/plugins/sensing/setup.sh      # on the Jetson host    -> setup_host.sh
   src/plugins/sensing/setup.sh      # in the devcontainer   -> setup_container.sh
   src/plugins/sensing/verify.sh     # anywhere, read-only

``setup.sh`` auto-detects the context; ``--host`` / ``--container`` override it.
Each script prints every privileged action it will take before the first
``sudo`` prompt and asks again per optional action. ``--yes`` accepts them all;
non-interactive stdin declines them all.

Host — first install
~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   src/plugins/sensing/setup_host.sh --install-drivers

This runs the vendor ``install.sh`` and stops. Select the overlay and reboot
before continuing:

.. code-block:: bash

   sudo /opt/nvidia/jetson-io/jetson-io.py   # Configure Jetson AGX CSI Connector
                                             # -> Jetson Sensing SG10A_AGON_G2M_A1 S56Cx1 SHF3Lx6

The package is autodetected under ``~/Sensing/``, ``~``, ``/home/*/Sensing/``
and ``/opt/sensing/``; ``--pkg`` or ``$SENSING_PKG_DIR`` overrides.

Host — every boot
~~~~~~~~~~~~~~~~~

.. code-block:: bash

   src/plugins/sensing/setup_host.sh [--fps 30] [--free-run|--trigger-sync] [--service]

The vendor ``install.sh`` never copies the sensor ``.ko`` files into
``/lib/modules``, so nothing auto-loads them and ``/dev/video*`` is empty after
every reboot. That is the most common cause of "the cameras stopped working".
``setup_host.sh`` loads them, then offers to install ``sensing-camera.service``
so it happens at boot.

.. note::

   The unit is ordered ``Before=nvargus-daemon.service``, **not**
   ``After=multi-user.target``. ``nvargus-daemon`` is itself part of
   ``multi-user.target``; a daemon that starts before the sensors exist
   enumerates an empty camera list and never retries.

The vendor default slaves every sensor to the carrier's PWM trigger, which only
fires when **J19 pins 2 and 4 are strapped together** — without the strap the
camera opens fine and then delivers no frames, which looks like a software
hang. ``--free-run`` (the default) clears the trigger mode. Use
``--trigger-sync`` only when the strap is fitted and you need cross-camera sync.

Container
~~~~~~~~~

.. code-block:: bash

   src/plugins/sensing/setup_container.sh [--argus-include DIR] [--yes]

One thing the container cannot fix for itself: ``libnvargus_socketclient``
reaches ``nvargus-daemon`` through ``/tmp/argus_socket``, and a container gets
its own ``/tmp``. Add the bind mount to ``runArgs`` and rebuild:

.. code-block:: json

   "-v", "/tmp/argus_socket:/tmp/argus_socket"

The script also checks for the Argus headers (``v4l-utils``, EGL headers,
``nvcc``), and offers to symlink an Argus tree it finds to
``/usr/src/jetson_multimedia_api/argus``.

Build
-----

.. code-block:: bash

   cmake -B build -DBUILD_PLUGIN_SENSING=ON
   cmake --build build --target camera_plugin_sensing --parallel

Both dependencies live outside the repo. On a Jetson host they come from
``sudo apt install nvidia-l4t-jetson-multimedia-api``. In a container, copy the
tree in and point CMake at it:

.. code-block:: bash

   cmake -B build -DBUILD_PLUGIN_SENSING=ON \
       -DARGUS_INCLUDE_DIRS=$HOME/Sensing/argus/include \
       -DJETSON_MMAPI_DIR=$HOME/Sensing/jetson_multimedia_api

.. warning::

   Argus needs NVIDIA's EGL. GLVND picks the EGL vendor from ``DISPLAY``, and
   Tegra's EGL cannot drive an Xvfb or forwarded X server, so it loses the probe
   to Mesa and every Argus-to-CUDA path fails. The plugin clears ``DISPLAY``
   itself before the first EGL call and refuses to start on a non-NVIDIA vendor,
   but anything else in the process that renders will be affected by this.

Sensor ids are not ``/dev/video`` numbers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``sensor=`` in ``--add-stream`` is the **Argus sensor id**, which follows
device-tree module order. On this overlay ids 0–3 are the S56C group and 4–9 the
SHF3L ports. Re-derive after any overlay change:

.. code-block:: bash

   for i in $(seq 0 9); do
     printf '%s ' "$i"
     cat /proc/device-tree/tegra-camera-platform/modules/module$i/badge
     echo
   done

Recording H.264
---------------

``output=<path>`` on a stream encodes that sensor on the Jetson V4L2 M2M engine
and writes raw Annex-B H.264 — no container, no timestamps. ``--add-stream`` is
repeatable, one per sensor:

.. code-block:: bash

   ./build/src/plugins/sensing/camera_plugin_sensing \
       --add-stream=sensor=2,output=./left.h264 \
       --add-stream=sensor=3,output=./right.h264 \
       --mcap-filename=./meta.mcap

Press ``Ctrl+C`` to stop. Run with ``--help`` for the full list; the knobs that
matter most:

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Option
     - Default
     - Description
   * - ``--add-stream=sensor=<id>[,output=<path>][,ipc=<socket>]``
     - (at least one required)
     - Add a capture stream. At least one of ``output`` / ``ipc`` is required;
       both may be given. Repeatable.
   * - ``--sensor-mode=N``
     - 0
     - Argus sensor mode. The S56C has only mode 0.
   * - ``--width=N`` / ``--height=N``
     - 1920 / 1080
     - Capture resolution
   * - ``--fps=N``
     - 30
     - Frame rate for all streams
   * - ``--bitrate=N``
     - 20000000
     - H.264 bitrate (bps)
   * - ``--gop=N``
     - ``fps*5``
     - IDR period in frames
   * - ``--mcap-filename=PATH``
     - none
     - Record per-frame metadata to an MCAP file
   * - ``--collection-prefix=PREFIX``
     - none
     - Push the same metadata over OpenXR instead. Mutually exclusive with
       ``--mcap-filename``.

Metadata
~~~~~~~~

Each frame emits a ``core.FrameMetadataSensingRecord`` (sequence number,
timestamps). ``--mcap-filename`` writes it to channel
``sensing_metadata/sensor<N>``; the binary schema is embedded, so ``mcap cat
--json meta.mcap`` decodes it without any Isaac headers.

``--collection-prefix`` pushes it via OpenXR ``SchemaPusher`` instead, for
recording into the same MCAP as the rest of a teleop session. The wiring is the
same as the OAK plugin's — see :doc:`oak` and :doc:`trackers`.

Playback
~~~~~~~~

Since the file carries no timestamps, a player has to be told the frame rate:

.. code-block:: bash

   ffplay -f h264 left.h264
   ffmpeg -f h264 -framerate 30 -i left.h264 -c copy left.mp4   # -framerate must match --fps

   # on the Jetson, decoded on the hardware engine that wrote it
   gst-launch-1.0 filesrc location=left.h264 ! h264parse ! nvv4l2decoder ! nv3dsink

To sanity-check a file with no tools installed, the 5th byte after each ``00 00
01`` start code carries the NAL type in its low 5 bits — a healthy recording
opens ``67`` (SPS), ``68`` (PPS), ``65`` (IDR): ``xxd -l 16 left.h264``.

Live streaming with camera_viz
------------------------------

``ipc=<socket>`` serves a sensor's frames to another process as **CUDA device
memory** — RGBA8, no encode, no host round-trip — and
:code-file:`camera_viz <examples/camera_viz/README.md>` consumes it with
``type: cuda_ipc``. It is independent of ``output=``; an ``ipc``-only stream
never starts an encoder. Measured on an AGX Orin at 1920×1080: **~1 ms** from
producer timestamp to consumer receipt, sustained at 60 fps.

.. code-block:: bash

   # terminal 1 — producer
   ./build/src/plugins/sensing/camera_plugin_sensing \
       --add-stream=sensor=2,ipc=/tmp/sensing2.sock --width=1920 --height=1080

   # terminal 2 — viewer
   cd examples/camera_viz
   ./camera_viz.sh setup                                     # one-time
   ./camera_viz.sh run configs/cuda_ipc.yaml --mode window   # desktop window
   ./camera_viz.sh run configs/cuda_ipc.yaml                 # XR headset

:code-file:`configs/cuda_ipc.yaml <examples/camera_viz/configs/cuda_ipc.yaml>`
needs only the socket path and the frame size:

.. code-block:: yaml

   cameras:
     - name: cam
       type: cuda_ipc
       socket: /tmp/sensing2.sock   # must match the producer's ipc= path
       width: 1920                  # must match what the producer serves
       height: 1080

Order does not matter — the source retries until the socket appears and survives
the producer restarting under it. ``width``/``height`` are checked during the
handshake and a mismatch is refused rather than rendered at the wrong stride.
**One consumer at a time**: the producer serves whoever connected most recently,
so a second viewer silently takes the feed from the first.

Testing without a camera
~~~~~~~~~~~~~~~~~~~~~~~~

``sensing_ipc_testsrc`` publishes an animated pattern over the same protocol. It
needs CUDA only — no Argus, no encoder — so the viewer can be developed with
nothing attached:

.. code-block:: bash

   cmake --build build --target sensing_ipc_testsrc
   ./build/src/plugins/sensing/sensing_ipc_testsrc --socket=/tmp/sensing2.sock \
       --width=1920 --height=1080 --fps=60

Each frame carries its 16-bit frame number as a binary bar across the top, so a
stale or torn frame is visible rather than merely suspected.

.. note::

   Legacy CUDA IPC does not work on Tegra and fails misleadingly:
   ``cudaIpcGetMemHandle`` returns ``cudaSuccess`` in the producer, then the
   consumer's ``cudaIpcOpenMemHandle`` fails with ``cudaErrorInvalidValue``. The
   transport therefore uses the virtual-memory-management API — ``cuMemCreate``
   plus ``cuMemExportToShareableHandle`` to a POSIX fd, passed over the Unix
   socket with ``SCM_RIGHTS``. Do not rewrite it back to
   ``cudaIpcMemHandle_t``. The wire format lives in
   :code-file:`src/plugins/sensing/core/cuda_ipc_protocol.hpp` and is
   re-declared by the consumer in
   :code-file:`examples/camera_viz/sources/cuda_ipc.py`, so the two change
   together.

Troubleshooting
---------------

Run ``verify.sh`` first — it names the fixing script for each failure.

.. list-table::
   :widths: 45 55
   :header-rows: 1

   * - Symptom
     - Cause and fix
   * - No ``/dev/video*`` after reboot
     - Drivers not loaded. Run ``setup_host.sh``, then install the service.
   * - Camera opens, no frames
     - Sensor slaved to an absent trigger. ``setup_host.sh --free-run``.
   * - Argus finds no cameras
     - ``nvargus-daemon`` started before the drivers.
       ``sudo systemctl restart nvargus-daemon``.
   * - ``EGL_NO_STREAM_KHR``, or ``NvBufSurfaceMapEglImage`` "Failed to create
       EGLImage"
     - EGL resolved to Mesa, not NVIDIA. Unset ``DISPLAY``, or point it at an X
       server Tegra EGL can drive.
   * - ``Connection refused`` on every Argus call right after restarting
       ``nvargus-daemon``
     - The container bind-mounts ``/tmp/argus_socket`` as a *file*; the daemon
       unlinks and recreates it, so the mount pins a deleted inode
       (``grep argus /proc/self/mountinfo`` shows ``//deleted``). Mount the
       host's ``/tmp`` and symlink instead, or restart the container.
   * - ``/tmp/argus_socket`` is a *directory*
     - The container started before ``nvargus-daemon``, so Docker created the
       missing bind source.
       ``sudo rmdir /tmp/argus_socket && sudo systemctl restart nvargus-daemon``.
   * - ``insmod: invalid module format``
     - Kernel is not ``5.15.148-tegra``; the prebuilt ``.ko`` files will not
       load.
   * - ``argus_camera: command not found`` in the container
     - It is installed at ``/usr/local/bin`` on the *host*.
       ``setup_container.sh`` offers to link a built copy.
