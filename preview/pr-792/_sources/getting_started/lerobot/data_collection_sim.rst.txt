.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Data Collection in Sim
======================

Collect SO-101 demonstrations in simulation with `NVIDIA Isaac Lab
<https://isaac-sim.github.io/IsaacLab>`_, on the cube-stacking task. You drive the simulated
follower through Isaac Teleop (see :doc:`devices`) and record episodes to an HDF5 dataset.

Two SO-101 stack tasks are registered in Isaac Lab:

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Task id
     - Use
   * - ``IsaacContrib-Stack-Cube-SO101-IK-Abs-v0``
     - Absolute-pose IK + Isaac Teleop teleoperation (use this for data collection).
   * - ``IsaacContrib-Stack-Cube-SO101-v0``
     - Joint-position control baseline (no teleop).

Before you start
----------------

.. important::

   Both steps below are **required** — complete them first. The teleoperation and recording
   commands later on will not work until you have.

**Step 1 — Install Isaac Lab.** Follow the `Isaac Lab installation guide`_ to set up the ``Lab``
repository, then run every script through its launcher: ``./isaaclab.sh -p <script> ...`` (or
plain ``python`` inside the activated Isaac Lab environment). The SO-101 USD assets stream from
the NVIDIA Nucleus server, so there is no manual asset download.

**Step 2 — Set up CloudXR and connect a headset.** XR teleoperation needs CloudXR and a headset,
the same as the real flow — follow the :doc:`/getting_started/quick_start` and the
`CloudXR teleoperation in Isaac Lab`_ guide. CloudXR auto-launches by default; pick the profile
with ``--cloudxr_env`` (``cloudxrjs`` for Quest/Pico, ``avp`` for Apple Vision Pro, ``none`` to
disable). No physical headset? Open the CloudXR web client in a desktop browser, which emulates a
headset.

Collect Teleop Data
-------------------

.. tab-set::

   .. tab-item:: XR controller

      The controller pose drives the simulated follower's end-effector through the clutch + IK
      pipeline, streamed over CloudXR — the same controls as on real hardware.

      #. **(Optional) Try teleoperation without recording.** A good way to check the setup first:

         .. code-block:: bash

            ./isaaclab.sh -p scripts/environments/teleoperation/teleop_se3_agent.py \
                --task IsaacContrib-Stack-Cube-SO101-IK-Abs-v0 \
                --xr \
                --viz kit

         ``--xr`` enables the XR/CloudXR path and ``--viz kit`` opens the Omniverse Kit viewport.
         Squeeze and hold the grip to engage the clutch and move the arm; the trigger controls the
         gripper.

      #. **Record a dataset.** ``record_demos.py`` runs the same teleoperation while saving
         episodes to HDF5. It records ``--num_demos`` demonstrations, marking one successful after
         ``--num_success_steps`` consecutive success frames:

         .. code-block:: bash

            ./isaaclab.sh -p scripts/tools/record_demos.py \
                --task IsaacContrib-Stack-Cube-SO101-IK-Abs-v0 \
                --dataset_file ./datasets/so101_stack_demos.hdf5 \
                --num_demos 10 \
                --step_hz 30 \
                --xr \
                --viz kit

         The demos are written to the ``--dataset_file`` path in HDF5 format.

   .. tab-item:: SO-101 Leader

      .. admonition:: 🚧 Work in progress
         :class: caution

         Driving the simulated follower from an **SO-101 Leader** arm is **not yet supported in
         Isaac Lab** — Isaac Lab has no joint-space leader device, and the SO-101 stack task is
         wired only for the XR controller. Sim leader support is planned; until then, use the
         leader arm on the real robot (:doc:`data_collection_real`).

Convert to LeRobot Dataset
--------------------------

.. admonition:: 🚧 Work in progress
   :class: caution

   **Export to a LeRobot dataset.** Converting these sim HDF5 demos to the
   :doc:`LeRobot dataset format <training_groot>` is **not yet provided** for the stack task. The
   closest reference is the locomanipulation converter `convert_dataset.py`_ from the ``develop``
   branch in Isaac Lab, which targets a different task and must be adapted.

..
   References
.. _Isaac Lab installation guide: https://isaac-sim.github.io/IsaacLab/develop/source/setup/installation/index.html#isaaclab-installation-root
.. _CloudXR teleoperation in Isaac Lab: https://isaac-sim.github.io/IsaacLab/develop/source/how-to/cloudxr_teleoperation.html
.. _convert_dataset.py: https://github.com/isaac-sim/IsaacLab/blob/develop/scripts/imitation_learning/locomanipulation_sdg/gr00t/convert_dataset.py
