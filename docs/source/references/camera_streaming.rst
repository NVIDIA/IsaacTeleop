.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Camera Streaming
================

``camera_viz`` is the reference camera-streaming sample built on :doc:`Televiz
</getting_started/televiz>` (``isaacteleop.viz``). It captures frames from one or more cameras and
visualizes them on a desktop window or an XR headset — one plane per camera, aspect-fit — and can
stream a robot's cameras to a remote workstation over the network.

The sample lives at :code-dir:`examples/camera_viz/ <examples/camera_viz>`; this page summarizes how
it works. For the exact command surface and flags, see the
:code-file:`README <examples/camera_viz/README.md>`.

.. figure:: ../_static/televiz_2d.gif
   :alt: camera_viz in window mode with synthetic multi-camera feeds
   :width: 420px
   :class: no-image-zoom

   ``camera_viz`` in XR mode — one plane per camera.

.. contents:: On this page
   :local:
   :depth: 2

Modes
-----

.. list-table::
   :header-rows: 1
   :widths: 16 84

   * - Mode
     - What it does
   * - **Direct**
     - The workstation runs the viewer with cameras attached locally (``source: local``).
   * - **Split**
     - The robot runs a sender that ships RTP H.264 to a workstation receiver (``source: rtp``).
       Wired Ethernet only.

Supported cameras
-----------------

The camera kind is selected per entry by the YAML ``type:`` field:

.. list-table::
   :header-rows: 1
   :widths: 16 84

   * - ``type:``
     - Notes
   * - ``synthetic``
     - GPU test pattern — no hardware. ``stereo: true`` adds a ``disparity_px`` offset between eyes.
   * - ``v4l2``
     - USB / UVC cameras — anything ``v4l2-ctl --list-formats-ext`` reports.
   * - ``oakd``
     - OAK-D mono RGB / LEFT / RIGHT (stereo not yet wired).
   * - ``zed``
     - ZED 2 / Mini / X One; mono or ``stereo: true`` (per-eye SDK retrieve, zero-copy on the GPU).
   * - ``video``
     - Video-file replay (anything OpenCV's FFmpeg backend reads) — preview / Televiz testing
       without a camera. Loops by default; ``stereo: true`` splits side-by-side recordings into
       eyes (viewer only).

Output goes to a window or an XR headset. Stereo cameras render true side-by-side stereo in XR;
window mode shows the left eye. XR placement lock modes are ``world`` / ``head`` / ``lazy``.

How it works
------------

The sample is organized so that capture, transport, and visualization are cleanly separated, with
Televiz as the compositor at the end of the chain:

.. code-block:: text
   :class: code-100col

   camera_viz/
   ├── camera_viz.sh        — CLI: setup / loopback / run / deploy / service-*
   ├── camera_viz.py        — receiver / viewer (drives a Televiz VizSession)
   ├── camera_streamer.py   — robot-side RTP sender (per-camera supervisor)
   ├── pipeline/            — source ABC + threaded runner
   ├── placements/          — XR lock-mode strategies (world / head / lazy)
   ├── sources/             — V4L2 / OAK-D / ZED / synthetic / video replay / rtp_h264
   ├── transports/          — RTP sender + receiver (native + GStreamer)
   ├── codec/               — native NVENC / NVDEC pybind module
   ├── configs/             — one YAML per camera kind
   └── scripts/             — installer + systemd unit template

- **Sources** (:code-dir:`sources/ <examples/camera_viz/sources>`) implement a common source ABC and
  hand frames to a threaded runner in :code-dir:`pipeline/ <examples/camera_viz/pipeline>`. Each
  source produces GPU frames where possible — e.g. the ZED source uses ``retrieve_image(MEM.GPU)`` so
  BGRA8 stays in VRAM and a CUDA kernel channel-swaps into contiguous RGBA with no host round-trip.
- **The viewer** (:code-file:`camera_viz.py <examples/camera_viz/camera_viz.py>`) creates a
  ``VizSession`` and adds one ``QuadLayer`` per enabled camera, then submits each frame to its layer
  and calls ``render()`` once per frame. Stereo cameras submit both eyes.
- **Transport** (:code-dir:`transports/ <examples/camera_viz/transports>`) carries the split mode:
  an RTP H.264 sender on the robot and a receiver on the workstation, with a native NVENC/NVDEC codec
  module (:code-dir:`codec/ <examples/camera_viz/codec>`) or a GStreamer fallback.
- **Placement** (:code-dir:`placements/ <examples/camera_viz/placements>`) holds the XR lock-mode
  strategies. Placement is application policy — Televiz only renders a layer at whatever pose the app
  sets each frame.

Setup
-----

One-time setup installs the sample's Python environment — no source build required:

.. code-block:: bash

   examples/camera_viz/camera_viz.sh setup
   source examples/camera_viz/.venv/bin/activate

``setup`` installs ``isaacteleop`` (which bundles Televiz) and every other Python dependency from
PyPI into ``.venv/`` via ``uv``, builds the native NVENC/NVDEC codec, and probes system packages
(GStreamer plugins, cairo / girepository headers, JetPack ``cuda-nvrtc`` + ``ld.so`` wiring). When
something is missing it prints the exact ``apt-get`` line and prompts ``[y/N]`` — answering ``n`` or
running non-interactively aborts.

Useful flags: ``--no-{v4l2,oakd,rtp}``, ``--with-zed``, ``--sender-only``, ``--jetson``. Pass
``--venv PATH`` to install into an existing virtual environment. To develop against a locally built
wheel instead of the PyPI release, pass ``--wheel <path>`` (see
:doc:`/getting_started/build_from_source/index`).

Running
-------

Direct (cameras on the workstation)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Set ``source: local`` in the config and run the viewer:

.. code-block:: bash

   ./camera_viz.sh run configs/v4l2.yaml

Swap the config for ``oakd.yaml``, ``zed.yaml``, ``synthetic.yaml``, ``synthetic_stereo.yaml``,
``multi_camera.yaml``, or ``video.yaml`` (file replay — point ``path:`` at any recording).

Split (robot → workstation over RTP)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. warning::

   **Wired networks only.** There is no retransmit or FEC — one lost packet corrupts one frame until
   the next IDR (default every 5 s).

Set ``source: rtp`` in the config, export the robot/streaming credentials once per shell, then
deploy the sender and run the viewer:

.. code-block:: bash

   export REMOTE_HOST=10.0.0.5 REMOTE_USER=nvidia
   export STREAMING_HOST=10.0.0.42                  # workstation IP

   ./camera_viz.sh deploy configs/v4l2.yaml         # full deploy + systemd unit on the robot
   ./camera_viz.sh run    configs/v4l2.yaml         # viewer on the workstation

``deploy`` rsyncs the source to the robot, installs sender dependencies, renders a
``camera-streamer.service`` systemd user unit (injecting ``--host`` from ``$STREAMING_HOST`` without
editing the YAML on disk), and enables it. Operate the running unit with
``./camera_viz.sh service-{status,logs,restart}``. The sender retries forever across unplug, SDK
errors, and network blips.

Loopback
^^^^^^^^

``./camera_viz.sh loopback configs/v4l2.yaml`` runs the sender and viewer together on ``127.0.0.1``
— the quickest way to smoke-test the RTP path on one machine.

Configuration
-------------

A single YAML drives both capture and visualization. Each ``cameras:`` entry becomes its own plane
(and, in split mode, its own RTP port). Abbreviated:

.. code-block:: yaml

   source: local | rtp
   streaming:
     host: 192.168.1.100         # workstation IP (overridden at deploy time)
   encoder: auto | native | gstreamer

   cameras:
     - name: cam
       enabled: true
       type: v4l2                # v4l2 | oakd | zed | synthetic | video
       width: 2560               # video: optional — defaults to the file's size
       height: 720
       fps: 30
       stereo: false             # zed / synthetic / video only — per-eye capture + SBS in XR
       rtp:
         port: 5000              # left eye when stereo
         port_right: 5001        # required when stereo + source: rtp
         bitrate_mbps: 15

   display:
     mode: window | xr
     window: { width, height }
     xr:     { near_z, far_z }
     clear_color: [r, g, b, a]
     placements:
       cam:
         lock_mode: lazy         # world | head | lazy
         distance: 1.5
         # size: [w_m, h_m]
         # stereo_baseline_mm: 0

See the :code-dir:`configs/ <examples/camera_viz/configs>` directory for a complete, commented YAML
per camera kind.

Lock modes (XR)
^^^^^^^^^^^^^^^

How a camera plane is positioned relative to the operator's head each frame:

.. list-table::
   :header-rows: 1
   :widths: 16 84

   * - Mode
     - Behavior
   * - ``world``
     - Placed once in front of you and stays put.
   * - ``head``
     - Follows your head every frame.
   * - ``lazy``
     - World-locked, but re-snaps in front of you when you look away (default).

Lazy-mode knobs live under ``placements.<name>``: ``look_away_angle_deg``, ``reposition_distance``,
``reposition_delay_s``, ``transition_duration_s``.

Sharing the XR session with TeleopSession
-----------------------------------------

Only one OpenXR session is allowed per process, so when this sample runs alongside teleoperation the
``VizSession`` owns the session and hands its handles to ``TeleopSession`` / ``DeviceIOSession``,
which then skip creating their own. The viewer builds the session with the trackers' required
extensions and forwards the handles through ``TeleopSessionConfig.oxr_handles``:

.. code-block:: python

   cfg.required_extensions = DeviceIOSession.get_required_extensions(trackers)
   viz_session = televiz.VizSession.create(cfg)

   config = TeleopSessionConfig(
       app_name="MyApp",
       pipeline=pipeline,
       oxr_handles=OpenXRSessionHandles(*viz_session.get_oxr_handles()),
   )

See the *Sharing the XR session* section of :doc:`/getting_started/televiz` for the full pattern
(imports, frame loop, and how the two sessions' lifecycles relate), and
:doc:`/getting_started/teleop_session` for the ``TeleopSession`` side.
