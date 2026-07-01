.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Data Collection in Real
=======================

Record demonstrations on a physical SO-101 into a `LeRobot dataset
<https://huggingface.co/docs/lerobot/en/index>`_, driving the follower with either teleop device
(see :doc:`devices`). The example scripts live in ``examples/isaac_teleop_to_so101/`` in the
`LeRobot <https://github.com/huggingface/lerobot>`_ repository: ``teleoperate.py`` drives the arm
live, and ``record.py`` does the same while saving a dataset. Both take the same
``--robot.*`` / ``--teleop.*`` flags; ``--teleop.type`` selects the device
(``xr_controller`` | ``so101_leader``).

Before you start
----------------

#. A working **SO-101 follower** — assembled, motors set up, and calibrated. See
   `SO-101 support in LeRobot`_.

#. The **isaac-teleop extra** installed (``isaacteleop`` ships on public PyPI; its
   ``[cloudxr,retargeters]`` extras pull the CloudXR runtime bindings and the retargeter library):

   .. code-block:: bash

      uv pip install -e '.[isaac-teleop]'

#. Run the scripts from the example directory, and log in to the Hugging Face Hub — recorded
   datasets are pushed to the Hub by default (pass ``--dataset.push_to_hub=false`` to keep them
   local):

   .. code-block:: bash

      cd examples/isaac_teleop_to_so101
      huggingface-cli login

Then follow the steps for your teleop device:

.. tab-set::

   .. tab-item:: XR controller

      The controller pose drives the follower's end-effector through the clutch + IK pipeline,
      streamed over CloudXR.

      #. **Fetch the robot model.** The XR path solves inverse kinematics, so it needs the SO-101
         URDF and meshes (downloaded into ``./SO101/``):

         .. code-block:: bash

            python download_assets.py

      #. **Connect a headset.** Bring up CloudXR and connect your XR headset — follow the
         :doc:`/getting_started/quick_start`.

      #. **(Optional) Try teleoperation without recording.** A good way to check the setup before
         committing to a dataset:

         .. code-block:: bash

            python teleoperate.py \
                --robot.type=so101_follower \
                --robot.port=/dev/ttyACM0 \
                --robot.id=so101_follower_arm \
                --teleop.type=xr_controller

         Squeeze and hold the grip to engage the clutch and move the arm; the trigger controls the
         gripper. Release the grip to pause.

      #. **Record a dataset.** Add cameras and the dataset parameters:

         .. code-block:: bash

            python record.py \
                --robot.type=so101_follower \
                --robot.port=/dev/ttyACM0 \
                --robot.id=so101_follower_arm \
                --teleop.type=xr_controller \
                --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}}" \
                --dataset.repo_id=<hf_user>/<dataset_name> \
                --dataset.single_task="Pick up vial from rack on the left side" \
                --dataset.num_episodes=3 \
                --dataset.episode_time_s=20 \
                --dataset.reset_time_s=5

      .. note::

         **Customizing the reset pose.** On startup the XR path slews the arm to a built-in default
         reset pose (a comfortable mid-range pose) before handing control to the clutch — you do
         **not** need to record anything. To tailor it to your setup, back-drive the arm to the
         pose you want and run ``python override_reset_pose.py``; it writes ``reset_pose.json``
         (git-ignored, user-local), which takes priority over the default on the next run. Pass
         ``--reset_to_origin=false`` to skip the slew and keep the arm where it is.

   .. tab-item:: SO-101 Leader

      A back-drivable SO-101 leader arm mirrored 1:1 to the follower. Its joints are streamed by
      Isaac Teleop's ``so101_leader`` plugin, which the script launches for you.

      #. **Build the so101_leader plugin.** It is part of Isaac Teleop's C++ source, not the
         ``isaacteleop`` pip package, so build it from an Isaac Teleop checkout:

         .. code-block:: bash

            cmake -B build && cmake --build build --parallel && cmake --install build

         The binary lands at ``install/plugins/so101_leader/so101_leader_plugin``. For details see
         :ref:`so101-leader-plugin` and :doc:`/getting_started/build_from_source/index`.

      #. **Calibrate the leader** so the leader and follower agree on each joint's zero and range.
         This reuses the serial SO-101 leader's calibration (stored under ``so_leader/<id>.json``
         and reused on every run):

         .. code-block:: bash

            lerobot-calibrate \
                --teleop.type=so101_leader \
                --teleop.port=/dev/ttyACM1 \
                --teleop.id=so101_leader_arm

      #. **(Optional) Try teleoperation without recording.** ``--launch_plugin`` spawns the plugin
         after CloudXR is up; ``--teleop.port`` is the leader's serial port:

         .. code-block:: bash

            python teleoperate.py \
                --robot.type=so101_follower \
                --robot.port=/dev/ttyACM0 \
                --robot.id=so101_follower_arm \
                --teleop.type=so101_leader \
                --teleop.port=/dev/ttyACM1 \
                --teleop.id=so101_leader_arm \
                --launch_plugin=/path/to/IsaacTeleop/install/plugins/so101_leader/so101_leader_plugin

         Back-drive the leader arm by hand to move the follower.

      #. **Record a dataset.** Same flags as teleoperation, plus the cameras and dataset parameters
         (keep ``--launch_plugin`` so the plugin is started):

         .. code-block:: bash

            python record.py \
                --robot.type=so101_follower \
                --robot.port=/dev/ttyACM0 \
                --robot.id=so101_follower_arm \
                --teleop.type=so101_leader \
                --teleop.port=/dev/ttyACM1 \
                --teleop.id=so101_leader_arm \
                --launch_plugin=/path/to/IsaacTeleop/install/plugins/so101_leader/so101_leader_plugin \
                --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}}" \
                --dataset.repo_id=<hf_user>/<dataset_name> \
                --dataset.single_task="Pick up vial from rack on the left side" \
                --dataset.num_episodes=3 \
                --dataset.episode_time_s=20 \
                --dataset.reset_time_s=5

Recording controls
------------------

``record.py`` records ``--dataset.num_episodes`` episodes of ``--dataset.episode_time_s`` seconds
each, with a ``--dataset.reset_time_s`` window between episodes to reposition the scene. While
it is running, **press** these keys in the terminal where ``record.py`` is running — the example
reads them from that terminal, so they work over SSH and in a plain terminal (Linux/macOS), with
no desktop session required:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Key
     - Action
   * - Right arrow →
     - End the current episode early and save it.
   * - Left arrow ←
     - Discard the current take and re-record it.
   * - Escape
     - Stop after the current episode (already-saved episodes are kept).

Set ``LEROBOT_KEYBOARD_BACKEND`` to override how keys are read — ``auto`` (the default; uses the
terminal when one is attached, otherwise a global listener), ``stdin``, ``pynput``, or ``none``.
The dataset is written under ``$HF_LEROBOT_HOME/<repo_id>`` and pushed to the Hub when recording
finishes (unless ``--dataset.push_to_hub=false``). Next, train a policy on it:
:doc:`training_groot`.

.. _SO-101 support in LeRobot: https://huggingface.co/docs/lerobot/en/so101
