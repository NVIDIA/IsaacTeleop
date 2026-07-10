.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Camera Streaming
================

``camera_viz`` is the reference camera-streaming sample built on :doc:`Televiz
</getting_started/televiz>` (``isaacteleop.viz``). It captures frames from one or more cameras
and streams them to an XR headset — one plane per camera, aspect-fit — either directly or from a
robot to a workstation over the network (split mode). For development and debugging it can also
replay a video file in place of a camera, and render to a desktop window instead of the headset.

The sample lives at :code-dir:`examples/camera_viz/ <examples/camera_viz>`. This page walks you
from setup and a hardware-free first run to real cameras and the robot → workstation split mode.
For the exact command surface and flags, see the
:code-file:`README <examples/camera_viz/README.md>`.

.. figure:: ../_static/televiz_2d.gif
   :alt: camera_viz in window mode with synthetic multi-camera feeds
   :width: 420px
   :class: no-image-zoom

   ``camera_viz`` in XR mode — one plane per camera.

.. contents:: On this page
   :local:
   :depth: 2

Requirements
------------

- A workstation meeting the :doc:`system requirements </references/requirements>` (Ubuntu, NVIDIA
  GPU, CUDA driver) — every source hands frames to the renderer GPU-resident via CuPy.
- For the default XR mode, a running CloudXR server with a connected headset — follow the
  :doc:`quick start </getting_started/quick_start>` steps :ref:`run-cloudxr-server` and
  :ref:`connect-xr-headset`. No headset handy? ``--mode window`` renders to a desktop window
  instead and only needs a local display.

Setup
-----

Clone the repository if you haven't already (quick start step :ref:`check-out-code-base`), then
run the sample's one-time setup:

.. code-block:: bash

   examples/camera_viz/camera_viz.sh setup
   source examples/camera_viz/.venv/bin/activate

There is no need to install the ``isaacteleop`` pip package yourself — ``setup`` creates the
sample's own environment: it installs ``isaacteleop`` (which bundles Televiz) and every other
Python dependency from PyPI into ``.venv/`` via ``uv``, builds the native NVENC/NVDEC codec, and
probes system packages (GStreamer plugins, cairo / girepository headers, JetPack ``cuda-nvrtc`` +
``ld.so`` wiring). When something is missing it prints the exact ``apt-get`` line and prompts
``[y/N]`` — answering ``n`` or running non-interactively aborts.

By default ``setup`` provisions everything except ZED support; flags trim or extend that:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Flag
     - Effect
   * - ``--no-v4l2``
     - Skip USB / UVC webcam support (``opencv-python``).
   * - ``--no-oakd``
     - Skip OAK-D support (``depthai``).
   * - ``--no-rtp``
     - Skip split-mode dependencies: the GStreamer system packages and the native NVENC/NVDEC
       codec build. Direct mode still works.
   * - ``--with-zed``
     - Also build + install the ZED SDK's Python API (``pyzed``). Requires the ZED SDK on the
       machine (default ``/usr/local/zed``; override with ``--zed-sdk PATH``).
   * - ``--sender-only``
     - Split mode only — robot-side install of just the sender's dependencies.
   * - ``--jetson``
     - Split mode only — extra CUDA wiring JetPack images need on the robot.
   * - ``--venv PATH``
     - Install into an existing virtual environment instead of creating ``.venv/``.
   * - ``--wheel PATH``
     - Install a locally built ``isaacteleop`` wheel instead of the PyPI release — for developing
       Isaac Teleop itself (see :doc:`/getting_started/build_from_source/index`).

First run — no camera required
------------------------------

The video-replay source (``type: video``) plays a recording through exactly the same path a live
camera uses, so it doubles as the quickest end-to-end check and as a stand-in feed while the real
camera isn't available. A test clip ships with the repo and ``configs/video.yaml`` already points
at it:

.. code-block:: bash

   cd examples/camera_viz
   ./camera_viz.sh run configs/video.yaml                 # XR headset (default)
   ./camera_viz.sh run configs/video.yaml --mode window   # desktop window instead

**You should see** the terminal report the session and the source coming up::

   camera_viz: source=local, mode=xr, xr=True, 1 layer(s)
   [video] opening...
   [video] connected
   [video] streaming

and the clip looping on a plane in the headset — or in a desktop window (``mode=window,
xr=False``) with the ``--mode window`` override.

To replay your own video, set a custom ``path:`` in :code-file:`configs/video.yaml
<examples/camera_viz/configs/video.yaml>` — relative paths resolve against the YAML's directory.
``loop: false`` holds the last frame instead of rewinding; ``stereo: true`` splits a side-by-side
recording (e.g. from a ZED) into per-eye views.

Supported sources
-----------------

The source kind is selected by the ``type`` field of each entry in the YAML ``cameras`` list:

.. list-table::
   :header-rows: 1
   :widths: 16 84

   * - ``type:``
     - Notes
   * - ``v4l2``
     - USB / UVC cameras — anything ``v4l2-ctl --list-formats-ext`` reports.
   * - ``oakd``
     - OAK-D mono RGB / LEFT / RIGHT (stereo not yet wired).
   * - ``zed``
     - ZED 2 / Mini / X One; mono or ``stereo: true`` (per-eye SDK retrieve, zero-copy on the GPU).
   * - ``video``
     - Video-file replay (anything OpenCV's FFmpeg backend reads). Loops by default;
       ``stereo: true`` splits side-by-side recordings into eyes (viewer only).
   * - ``synthetic``
     - Debugging tool — GPU-generated test pattern, no hardware or file.

Running with a real camera
--------------------------

Attach the camera to the machine that runs the viewer, keep ``source: local`` in the config, and
run with the matching config:

.. code-block:: bash

   ./camera_viz.sh run configs/v4l2.yaml     # or oakd.yaml / zed.yaml

**You should see** the same startup lines as above with the camera's tag (``[v4l2]``,
``[oakd]``, ``[zed]``) and the live feed. Multiple entries in the ``cameras`` list render as one
plane each.

Display modes
-------------

XR is the default: each camera renders as its own plane in the headset via the active OpenXR
runtime, and stereo sources (``stereo: true``) render true side-by-side stereo. Pass
``--mode window`` (or set ``display.mode: window`` in the YAML) to render to a desktop window
instead — no headset or runtime needed; stereo shows the left eye.

In XR, how a plane follows the operator's head is the per-camera ``lock_mode`` under
``display.placements.<name>``:

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

Lazy-mode knobs live under ``placements.<name>``: ``look_away_angle_deg``,
``reposition_distance``, ``reposition_delay_s``, ``transition_duration_s``.

Split mode — robot → workstation over RTP
-----------------------------------------

Split mode runs the capture side on the robot (``camera_streamer.py``) and ships RTP H.264 to
the viewer on the workstation (``source: rtp``).

.. warning::

   Split mode adds a full extra encode/decode hop — NVENC on the robot, UDP, NVDEC on the
   workstation — so it is **not recommended** when a camera can attach directly to the viewer
   machine; run direct instead. Reach for it only when the cameras are physically on the robot.
   Wired networks only: there is no retransmit or FEC — one lost packet corrupts one frame until
   the next IDR (default every 5 s).

In split mode every camera entry must pin ``width``, ``height``, and ``fps`` in the YAML — the
receiver sizes its decoder from the config, not from the wire.

Set ``source: rtp`` in the config, export the robot/streaming credentials once per shell, then
deploy the sender and run the viewer:

.. code-block:: bash

   export REMOTE_HOST=10.0.0.5 REMOTE_USER=nvidia
   export STREAMING_HOST=10.0.0.42                  # workstation IP

   ./camera_viz.sh deploy configs/v4l2.yaml         # full deploy + systemd unit on the robot
   ./camera_viz.sh run    configs/v4l2.yaml         # viewer on the workstation

``deploy`` rsyncs the source to the robot, installs sender dependencies, renders a
``camera-streamer.service`` systemd user unit (injecting ``--host`` from ``$STREAMING_HOST``
without editing the YAML on disk), and enables it. Operate the running unit with
``./camera_viz.sh service-{status,logs,restart}``. The sender retries forever across unplug, SDK
errors, and network blips.

Loopback
^^^^^^^^

Loopback is a testing / debugging aid, not a deployment mode: ``./camera_viz.sh loopback
configs/v4l2.yaml`` runs the sender and viewer together on ``127.0.0.1`` — the quickest way to
smoke-test the RTP path on one machine. It also works camera-free with a mono ``type: video``
entry (set ``width`` / ``height`` / ``fps``).

Configuration
-------------

A single YAML drives both capture and visualization. Each entry in the ``cameras`` list becomes
its own plane (and, in split mode, its own RTP port). Abbreviated:

.. code-block:: yaml

   source: local | rtp
   streaming:
     host: 192.168.1.100         # workstation IP (overridden at deploy time)
   encoder: auto | native | gstreamer

   cameras:
     - name: cam
       enabled: true
       type: v4l2                # v4l2 | oakd | zed | video | synthetic
       width: 2560               # video: optional — defaults to the file's size
       height: 720               # (required when source: rtp)
       fps: 30
       stereo: false             # zed / video / synthetic — per-eye capture + SBS in XR
       path: clip.mp4            # video only — file to replay, relative to this YAML
       loop: true                # video only — rewind at end of file
       rtp:
         port: 5000              # left eye when stereo
         port_right: 5001        # required when stereo + source: rtp
         bitrate_mbps: 15

   display:
     mode: xr | window           # default: xr
     window: { width, height }
     xr:     { near_z, far_z }
     clear_color: [r, g, b, a]
     placements:
       cam:
         lock_mode: lazy         # world | head | lazy
         distance: 1.5
         # size: [w_m, h_m]
         # stereo_baseline_mm: 0

See the :code-dir:`configs/ <examples/camera_viz/configs>` directory for a complete, commented
YAML per source kind.

Troubleshooting
---------------

- **The XR session fails to create** — the default mode needs the CloudXR server running and a
  headset connected (quick start steps :ref:`run-cloudxr-server` and :ref:`connect-xr-headset`);
  pass ``--mode window`` to render to a desktop window instead.
- **No window appears over SSH** — ``--mode window`` needs a local display; run on the machine
  you're sitting at, or use a video-capable remote desktop.
- **"video source: no such file"** — relative ``path:`` values resolve against the YAML's
  directory (``configs/``), not the directory you launched from.
- **The shipped test clip won't open** — it lives in Git LFS; if ``test_data/recording.mp4`` is
  a tiny text file, run ``git lfs install && git lfs pull``.
- **A source fails asking for CuPy / CUDA** — check ``nvidia-smi`` works and setup completed;
  all sources allocate their frame buffers on the GPU.
- **Split mode renders nothing** — check the sender is up (``./camera_viz.sh service-status``),
  ``$STREAMING_HOST`` was the workstation's IP at deploy time, and UDP ports (default 5000+)
  aren't firewalled.
- **Not sure which side is stuck?** — set ``verbose: true`` at the top of the YAML for periodic
  per-source breadcrumbs on both ends.

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
   ├── sources/             — V4L2 / OAK-D / ZED / video replay / synthetic / rtp_h264
   ├── transports/          — RTP sender + receiver (native + GStreamer)
   ├── codec/               — native NVENC / NVDEC pybind module
   ├── configs/             — one YAML per source kind
   ├── test_data/           — sample replay clip (Git LFS)
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
