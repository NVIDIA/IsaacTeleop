.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Generic Joint-Space Device
==========================

A reusable device path for any **joint-encoder source** -- leader arms, exoskeletons, haptic
gloves, or other articulated input devices. A device streams a name-keyed ``JointStateOutput``
FlatBuffer over the OpenXR tensor transport; one schema, one tracker, one source, and one
retargeter serve them all, so adding a new joint-space device is just a new **plugin** plus a
small **config**.

The **SO-101 leader arm** (`TheRobotStudio SO-ARM100 <https://github.com/TheRobotStudio/SO-ARM100>`_,
6 Feetech STS3215 bus servos) is the reference instance.

At a glance
-----------

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Layer
     - Component
   * - Schema
     - :code-file:`src/core/schema/fbs/joint_state.fbs` -- ``JointState`` (name + position +
       optional velocity/effort) and ``JointStateOutput`` (a vector of joints + ``device_id``).
   * - Plugin
     - :code-dir:`src/plugins/so101_leader` -- pushes ``JointStateOutput`` via ``SchemaPusher``.
       Ships a synthetic backend; the real Feetech/serial read is a marked seam.
   * - Tracker
     - ``JointStateTracker`` (facade) with live (``LiveJointStateTrackerImpl``) and MCAP-replay
       (``ReplayJointStateTrackerImpl``) backends, registered in the live/replay factories.
   * - Source
     - ``JointStateSource`` (``IDeviceIOSource``) -- converts the FlatBuffer into a name-keyed
       group of joint positions for the retargeting graph.
   * - Retargeter
     - ``JointStateRetargeter`` -- ``joint`` (mirror) or ``ee_pose`` (URDF FK) mode. See
       :doc:`/references/retargeting/joint_space`.

Data schema
-----------

Joints are modeled as **name -> value** records so consumers read them by name, independent of
wire order:

.. code-block:: idl
   :class: code-100col

   table JointState {
     name: string (id: 0, key);   // e.g. "shoulder_pan", "gripper"
     position: float (id: 1);     // [rad] revolute, [m] prismatic
     velocity: float (id: 2);     // optional (JointStateOutput.has_velocity)
     effort: float (id: 3);       // optional (JointStateOutput.has_effort)
     valid: bool = true (id: 4);
   }

   table JointStateOutput {
     joints: [JointState] (id: 0);
     device_id: string (id: 1);
     has_velocity: bool (id: 2);
     has_effort: bool (id: 3);
     ee_pose: Pose (id: 4);       // RESERVED: device-side FK; not consumed yet
     ee_pose_valid: bool (id: 5);
   }

The gripper is just another named DOF (conventionally ``"gripper"``). ``velocity``, ``effort``,
and ``ee_pose`` are optional/reserved: the reference plugin and ``JointStateSource`` populate and
surface joint **positions** only.

The SO-101 leader plugin
------------------------

``so101_leader`` reads the six SO-101 servos (``shoulder_pan, shoulder_lift, elbow_flex,
wrist_flex, wrist_roll, gripper``) and pushes them to a tensor collection. To keep the example
hardware-free and headless it ships a **synthetic backend**; the real Feetech read (via LeRobot's
``FeetechMotorsBus`` + calibration) is the marked seam in ``So101LeaderPlugin::read_hardware()``.

.. code-block:: bash

   # Synthetic backend (no hardware), default collection id "so101_leader":
   ./install/plugins/so101_leader/so101_leader_plugin

   # Reserved for the real serial backend + a custom collection id:
   ./install/plugins/so101_leader/so101_leader_plugin /dev/ttyACM0 so101_leader

The consumer side creates a ``JointStateSource(name=..., collection_id="so101_leader",
joint_names=[...])`` on the same ``collection_id``; ``TeleopSession`` discovers and polls the
``JointStateTracker`` each frame.

Record and replay
-----------------

The live tracker records to MCAP, and ``ReplayJointStateTrackerImpl`` replays it back with no
OpenXR runtime, so a recorded session drives the retargeting graph headlessly:

.. code-block:: python

   from isaacteleop.deviceio import McapRecordingConfig, McapReplayConfig
   from isaacteleop.teleop_session_manager import SessionMode, TeleopSession, TeleopSessionConfig

   # Record (live): TeleopSessionConfig(..., mcap_config=McapRecordingConfig("leader.mcap"))
   # Replay (headless): TeleopSessionConfig(..., mode=SessionMode.REPLAY,
   #                                        mcap_config=McapReplayConfig("leader.mcap"))

Add another joint-space device
------------------------------

Reuse everything above by writing only:

#. A **plugin** that reads your hardware and fills ``JointStateOutput`` (positions; optionally
   velocity/effort), modeled on :code-dir:`src/plugins/so101_leader`.
#. A **config**: a ``collection_id``, the device joint names, and -- for ``ee_pose`` mode -- a URDF
   and end-effector link.

The schema, ``JointStateTracker``, ``JointStateSource``, and ``JointStateRetargeter`` are unchanged.

.. seealso::

   :doc:`add_device` -- the general four-step device-plugin recipe (foot-pedal reference).

   :doc:`/references/retargeting/joint_space` -- the ``JointStateRetargeter`` (joint / EE modes),
   the end-to-end example, and validation.
