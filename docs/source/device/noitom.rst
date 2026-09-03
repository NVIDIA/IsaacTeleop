.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Noitom Motion Capture
=====================

Use a Noitom full-body motion-capture suit as an Isaac Teleop
``FullBodyTracker`` source. The optional ``noitom_mocap`` plugin reads avatar
updates from Noitom Hybrid Data Server (HDS), converts them to Isaac Teleop's
standard 24-joint ``FullBodyPose`` schema, and publishes them for recording,
replay, or G1 upper-body retargeting.

.. contents:: On this page
   :local:
   :depth: 2

Architecture
------------

The integration keeps the vendor SDK inside a plugin while applications consume
the same vendor-neutral tracker interface used by other full-body sources.

.. code-block:: text

   Noitom suit -> Axis Studio / HDS -> MocapApi TCP
       -> noitom_mocap_plugin
       -> OpenXR tensor collection "noitom_mocap", tensor "full_body"
       -> FullBodyTracker (vendor "body.noitom")
       -> recording / replay or Noitom-to-G1 retargeting

The plugin converts Noitom positions from centimeters to meters. Consumers select
it with vendor ID ``body.noitom`` and pass the collection ID and maximum FlatBuffer
size as vendor parameters. The default collection ID is ``noitom_mocap`` and the
default maximum sample size is 16 KiB.

Prerequisites
-------------

You need:

- a Noitom suit configured and calibrated in Axis Studio or another application
  that provides Noitom Hybrid Data Server;
- the HDS TCP endpoint reachable from the machine running Isaac Teleop;
- an Isaac Teleop source build; and
- Isaac Lab when running the G1 retargeting example.

The Noitom MocapApi SDK is optional and is not vendored in this repository. CMake
fetches it from `pnmocap/MocapApi <https://github.com/pnmocap/MocapApi>`_ when the
plugin is enabled.

Build and install
-----------------

From the Isaac Teleop repository root, enable the optional plugin and install the
Python package and plugin manifest:

.. code-block:: bash

   cmake -B build -DBUILD_PLUGIN_NOITOM_MOCAP=ON
   cmake --build build --target python_package noitom_mocap_plugin --parallel
   cmake --install build
   uv pip install --find-links=install/wheels "isaacteleop[cloudxr]"

For an offline SDK checkout, configure with
``-DNOITOM_MOCAP_API_ROOT=/path/to/MocapApi``.

Configure Hybrid Data Server
----------------------------

Start Axis Studio or the Noitom data-server application and enable its TCP data
stream. Then edit
:code-file:`src/plugins/noitom_mocap/plugin.yaml`
and set ``--host`` and ``--port`` to that HDS TCP endpoint. The checked-in values
may reflect the developer's network; they are not universal defaults.

Run the install step again after every manifest change:

.. code-block:: bash

   cmake --install build

This copies the updated manifest to
``install/plugins/noitom_mocap/plugin.yaml``. The source and installed manifests
must agree with the active HDS endpoint. Keep ``--collection-id=noitom_mocap``
unless the consuming application is configured with the same replacement ID.

Verify the stream
-----------------

Start the CloudXR/OpenXR runtime and HDS, then let a session launch the plugin or
start it manually:

.. code-block:: bash

   ./install/plugins/noitom_mocap/noitom_mocap_plugin

Print the frames received through DeviceIO from another terminal:

.. code-block:: bash

   python src/plugins/noitom_mocap/tools/noitom_mocap_printer.py --duration=10

If no frames appear, verify that HDS is streaming, its protocol is TCP, the host
and port are reachable, and the installed plugin manifest contains the latest
endpoint. Also verify that the producer and consumer use the same collection ID.

Record and replay
-----------------

The Noitom recording wrapper launches the plugin by default and records the
standard ``full_body`` channel:

.. code-block:: bash

   uv run python examples/noitom/record_noitom_full_body.py \
     10 examples/noitom/recordings/noitom_full_body.mcap

The resulting MCAP uses ``core.FullBodyPoseRecord``, so the generic full-body
replay example can read it:

.. code-block:: bash

   cd examples/mcap_record_replay/python
   uv sync
   uv run python replay_full_body.py \
     ../../noitom/recordings/noitom_full_body.mcap

Pass ``--no-plugin`` to the recording wrapper when the plugin is already running
manually.

G1 retargeting example
----------------------

The Noitom example registers an external Isaac Lab task based on
``Isaac-PickPlace-Locomanipulation-G1-Abs-v0``. Set ``ISAAC_TELEOP_ROOT`` and
``ISAACLAB_ROOT`` to your checkouts, then run:

.. code-block:: bash

   cd "$ISAACLAB_ROOT"
   PYTHONPATH="$ISAAC_TELEOP_ROOT/examples/noitom:${PYTHONPATH:-}" \
     ./isaaclab.sh -p scripts/environments/teleoperation/teleop_se3_agent.py \
     --task Isaac-PickPlace-Locomanipulation-G1-Noitom-Abs-v0 \
     --visualizer kit \
     --xr \
     --external_callback noitom_tasks.register_tasks

The task launches ``noitom_mocap_plugin`` through the plugin manager. For manual
plugin control, start the installed executable first and add
``NOITOM_MOCAP_AUTO_LAUNCH=0`` to the Isaac Lab command environment.

Retargeting and calibration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The retargeting pipeline maps the calibration-relative torso orientation and arm
bones to G1 Pink IK frame targets. The robot root remains fixed. The torso task
drives the waist joints with zero position cost, while elbow and shoulder
position tasks can be enabled or disabled independently.

After a teleop reset:

1. The previous neutral reference is cleared.
2. Hold a stable upper-body pose until a valid frame is received.
3. That frame becomes the neutral reference, and subsequent motion is applied
   relative to it.

With Kit visualization enabled, the incoming Noitom pose appears as a cyan stick
figure anchored to the robot pelvis. The default mapping and IK frame settings
are in :code-file:`examples/noitom/ik_config/noitom_to_g1.json`.

Troubleshooting
---------------

No plugin is found
~~~~~~~~~~~~~~~~~~

Run ``cmake --install build`` and confirm that
``install/plugins/noitom_mocap/`` contains both the executable and
``plugin.yaml``.

No full-body samples arrive
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Confirm that HDS is producing an avatar stream, not only displaying a local
preview. Check the TCP endpoint in both the source and installed manifests, then
use the printer command above before starting Isaac Lab. A consumer configured
for a different collection ID cannot see the stream.

Calibration does not complete
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stand still in a neutral upper-body pose and confirm that pelvis, torso,
shoulder, elbow, and wrist joints are valid. The task waits for a usable frame
rather than calibrating from incomplete data.

Motion appears delayed
~~~~~~~~~~~~~~~~~~~~~~

Confirm that only the intended plugin instance is connected to HDS and that the
network path is stable. Use the printer to distinguish delayed input from Isaac
Lab rendering or retargeting latency.

See also
--------

- :doc:`body_tracking` for the standard full-body schema and tracker concepts.
- :code-file:`examples/noitom/README.md` for the example's source-level guide.
- :code-file:`src/plugins/noitom_mocap/README.md` for plugin implementation and
  standalone run details.
- :code-file:`examples/noitom/noitom_retargeting.py` and
  :code-file:`examples/noitom/noitom_tasks.py` for the G1 pipeline.
