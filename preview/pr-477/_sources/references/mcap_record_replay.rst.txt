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
