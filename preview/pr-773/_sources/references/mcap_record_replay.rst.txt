.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

MCAP Recording & Replay
========================

Isaac Teleop supports recording live tracking data to `MCAP <https://mcap.dev/>`_
files and replaying them offline through the same retargeting pipeline — no
headset or OpenXR runtime required during replay.

Recording a Live Session
-------------------------

Pass an ``McapRecordingConfig`` in the ``mcap_config`` field while keeping the
default ``SessionMode.LIVE``.  ``TeleopSession`` automatically discovers
trackers from the pipeline, so you only need to provide the output filename:

.. code-block:: python

   from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig
   from isaacteleop.deviceio import McapRecordingConfig

   config = TeleopSessionConfig(
       app_name="MyApp",
       pipeline=pipeline,
       mcap_config=McapRecordingConfig("recording.mcap"),
   )

   with TeleopSession(config) as session:
       while True:
           result = session.step() # The tracker state is recorded to the MCAP file

When the context manager exits, the MCAP file is finalized and closed.

Auto-population and appending of tracker names
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``TeleopSession`` always auto-discovers trackers from the pipeline's DeviceIO
sources and uses each source's ``name`` as the MCAP channel name.  For
example, a pipeline with ``HeadSource(name="head")`` and
``HandsSource(name="hands")`` produces channels ``"head"`` and ``"hands"``.

Any ``(tracker, channel_name)`` pairs you pass explicitly via
``tracker_names`` are **appended** after the auto-discovered sources.  This is
useful for recording additional trackers that are not part of the pipeline:

.. code-block:: python

   from isaacteleop.deviceio import McapRecordingConfig

   extra_tracker = deviceio.HandTracker()

   mcap_config = McapRecordingConfig(
       "recording.mcap",
       [(extra_tracker, "extra_hands")],
   )

   # Final tracker list will be:
   #   [(head_source.tracker, "head"), (hands_source.tracker, "hands"),
   #    (extra_tracker, "extra_hands")]

Replaying a Recording
---------------------

Set ``mode=SessionMode.REPLAY`` and pass an ``McapReplayConfig``.  No OpenXR
session or headset connection is created — data is read directly from the MCAP
file:

.. code-block:: python

   from isaacteleop.teleop_session_manager import (
       TeleopSession,
       TeleopSessionConfig,
       SessionMode,
   )
   from isaacteleop.deviceio import McapReplayConfig

   config = TeleopSessionConfig(
       app_name="MyApp",
       pipeline=pipeline,
       mode=SessionMode.REPLAY,
       mcap_config=McapReplayConfig("recording.mcap"),
   )

   with TeleopSession(config) as session:
       while True:
           result = session.step()
           action = result["action"]
           # Process replayed action ...

Just like recording, trackers are auto-discovered from the pipeline and any
explicit ``tracker_names`` you provide are **appended** after them.  Use this
to add extra trackers that aren't part of the pipeline:

.. code-block:: python

   McapReplayConfig(
       "recording.mcap",
       [(extra_tracker, "extra_hands")],
   )

.. important::

   ``mcap_config`` is **required** when ``mode`` is ``SessionMode.REPLAY``.
   Omitting it raises ``ValueError``.

Runnable Example
----------------

A complete record / replay example lives at
``examples/mcap_record_replay/python/``:

- ``common.py`` — pipeline builders (``build_hand_pipeline()``,
  ``build_controller_pipeline()``, ``build_full_body_pipeline()``) plus the
  ``HandJoints`` retargeter and the bone tables used by the replay
  visualizers.
- ``record_hand.py`` / ``replay_hand.py`` — records the ``hands`` channel
  from a live OpenXR session and replays it with a `viser
  <https://viser.studio/>`_ visualization of both hand skeletons (joint cloud
  + skeleton).
- ``record_controller.py`` / ``replay_controller.py`` — records the
  ``controllers`` channel and replays it in viser, including a per-controller
  HUD (thumbstick, trigger, squeeze, button states).
- ``record_full_body.py`` / ``replay_full_body.py`` — records the
  ``full_body`` + ``controllers`` channels and replays the body skeleton in
  viser.

Each pipeline wires only the ``Source`` nodes it needs, so the resulting MCAP
contains exactly the matching channels.  To capture more data, add
additional source nodes (``HeadSource``, ``ControllersSource``, …) in
``common.py``.

For a live browser view of **all** human DeviceIO trackers at once (hands, head,
controllers, and full body), see ``examples/deviceio_live_view/python/``.

A C++ recorder lives at ``examples/mcap_record_replay/cpp/``:

- ``record_full_body.cpp`` — records the ``full_body`` channel by passing a
  ``core::McapRecordingConfig`` to ``DeviceIOSession::run()``. It uses the
  same channel base name as ``FullBodySource``, so the resulting file replays
  with ``replay_full_body.py``. ``python -m isaacteleop.rig rigs/full_body.yaml``
  runs it together with the CloudXR runtime and the full-body printer (see
  :ref:`rig-launcher`).

Recording
^^^^^^^^^

From the installed example directory:

.. code-block:: bash

   cd examples/mcap_record_replay/python
   uv sync
   uv run python record_hand.py            # 5 s → ../recordings/hands_<timestamp>.mcap
   uv run python record_hand.py 10         # record for 10 seconds
   uv run python record_hand.py 10 out.mcap  # custom output path

An active OpenXR runtime / headset must be connected, just like any other
live ``TeleopSession``.

Replaying
^^^^^^^^^

Replay runs headless — no headset required:

.. code-block:: bash

   uv run python replay_hand.py                       # newest file in ../recordings/
   uv run python replay_hand.py path/to/file.mcap     # explicit file
   uv run python replay_hand.py --loop                # repeat until Ctrl+C
   uv run python replay_hand.py --port 8090           # change viser port

Open the printed URL (default ``http://localhost:8080``) in a browser to see the
left (green) and right (blue) hand skeletons update each frame.

The ``record_controller.py`` / ``replay_controller.py`` and
``record_full_body.py`` / ``replay_full_body.py`` pairs use the same CLI
(positional MCAP path, ``--host``, ``--port``, ``--loop``).

API Reference
-------------

``SessionMode``
^^^^^^^^^^^^^^^

.. code-block:: python

   class SessionMode(Enum):
       LIVE = "live"
       REPLAY = "replay"

Determines whether ``TeleopSession`` creates a live OpenXR session or replays
from an MCAP file.

``McapRecordingConfig``
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   McapRecordingConfig(filename, tracker_names=None)

- **filename** — Path to the output MCAP file.
- **tracker_names** — Optional list of ``(tracker, channel_name)`` pairs.
  When empty, ``TeleopSession`` auto-populates from discovered sources.

``McapReplayConfig``
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   McapReplayConfig(filename, tracker_names=None)

- **filename** — Path to an existing MCAP file to replay.
- **tracker_names** — Optional list of ``(tracker, channel_name)`` pairs.
  When empty, ``TeleopSession`` auto-populates from discovered sources.
