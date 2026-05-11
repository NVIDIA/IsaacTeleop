==========
Unitree H2
==========

`isaac_ros_unitree_h2_teleop_bringup on GitHub
<https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_physical_ai/tree/main/isaac_ros_unitree_h2_teleop_bringup>`__

Overview
--------

Top-level launch file for Unitree H2 teleoperation combining AGILE locomotion, bimanual
inverse kinematics, and finger control. Supports XR teleoperation via
`Isaac Teleop <https://nvidia.github.io/IsaacTeleop>`__ and RViz interactive markers.

Both simulation and real hardware are supported.

Tutorial: Unitree H2 XR Teleop
-------------------------------

This tutorial walks through running whole-body XR teleoperation on the Unitree H2
humanoid robot. The application combines AGILE locomotion, bimanual inverse kinematics,
and finger control, all driven by an XR headset.

You will first run the application in MuJoCo simulation, then deploy on real hardware.

Prerequisites
^^^^^^^^^^^^^

.. note::

   This tutorial has been tested and qualified on **Jetson AGX Thor** for both simulation and
   real robot deployment. MuJoCo simulation is also supported on x86_64.

- `PICO 4 Ultra <https://www.picoxr.com/global/products/pico4-ultra>`__  headset or `Meta Quest 3 <https://www.meta.com/quest/quest-3/>`__ (if no XR headset is available, the emulator provided by
  `Isaac Teleop Core <https://nvidia.github.io/IsaacTeleop>`__ can be used instead)
- Unitree H2 robot powered on and connected to the host machine via Ethernet

Set Up Development Environment
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

#. Set up your Isaac ROS development environment by following the
   `Isaac ROS getting started guide
   <https://nvidia-isaac-ros.github.io/getting_started/index.html>`__.

#. Set up the Unitree H2 with a Jetson AGX Thor connected to it by following these guides:

   - `Unitree H2 Developer Guide <https://support.unitree.com/home/en/H2_developer/about_H2>`__
   - `Unitree H2 Quick Development <https://support.unitree.com/home/en/H2_developer/quick_development>`__

Build ``isaac_ros_unitree_h2_teleop_bringup``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

#. Follow the internal instructions to checkout the Isaac ROS mono-repo from GitLab.

   .. code:: bash

      git clone --branch devel/h2-gr00t-ra \
         ssh://git@gitlab-master.nvidia.com:12051/Isaac/isaac.git

#. Build and install Isaac ROS CLI

   `Build Isaac ROS CLI from source <https://gitlab-master.nvidia.com/Isaac/isaac/-/tree/main#build-isaac-ros-cli-from-source>`__

   We need the internal version to use the GitLab docker image cache.

#. Activate the Isaac ROS environment:

   .. code:: bash

      isaac-ros activate --build-local

   The build should be pulling containers from GitLab, rather than building everything from stratch, if it doesn't do that.

#. Build the package from source:

   .. code:: bash

      colcon build --packages-up-to isaac_ros_unitree_h2_teleop_bringup

#. Source the ROS workspace:

   .. note::

      Make sure to repeat this step in **every** terminal created inside the Isaac ROS environment. Because this package was built from source, the enclosing workspace must be sourced for ROS to be able to find the package's contents.

   .. code:: bash

      source install/setup.bash

Run CloudXR Server
^^^^^^^^^^^^^^^^^^

#. Start the CloudXR runtime. Be sure to review and accept the EULA:

   .. code:: bash

      python3 -m isaacteleop.cloudxr

   .. tip::

      To accept the EULA prompt in non-interactive settings, pass the flag:

      .. code:: bash

         python3 -m isaacteleop.cloudxr --accept-eula

#. In a **new** terminal, activate the Isaac ROS environment:

   .. code:: bash

      isaac-ros activate

#. Activate the CloudXR environment:

   .. code:: bash

      source ~/.cloudxr/run/cloudxr.env

#. Connect the XR headset to the teleop server. Follow the
   `headset connection guide <https://nvidia.github.io/IsaacTeleop/main/getting_started/quick_start.html#connect-an-xr-headset>`__.

   .. note::

      If you are running this on Thor, make sure to set the ``Video Codec`` to ``H.264``, otherwise
      the headset will fail to connect.

   .. warning::

      The world frame of the headset is defined as the position of the headset and controllers
      at the moment of connection. Stand still and face the robot before connecting to establish
      a consistent world frame. To reset the world frame, disconnect and reconnect the headset
      while stationary. On real hardware, ensure the robot is stopped (``blend_ratio`` set to
      ``0.0``) before disconnecting.

#. Launch the application:

   .. tab-set::

      .. tab-item:: MuJoCo Simulation

         #. Launch the teleop application:

            .. code:: bash

               ros2 launch isaac_ros_unitree_h2_teleop_bringup unitree_h2_teleop.launch.py \
                   hardware_type:=mujoco input_mode:=teleop

            This opens the MuJoCo viewer with the H2 robot. The virtual gantry holds the robot
            upright during startup. Press **G** to toggle the gantry on/off, and use **[** / **]**
            to shorten or lengthen the rope.

            .. note::

               In simulation, ``blend_ratio`` defaults to ``1.0`` so the policy is active
               immediately.

            ... code:: bash

               ros2 param set /safety_controller_with_hands blend_ratio 1.0

         #. With the controllers in your hands, start moving them. You should see the robot's arms
            track your movements in the MuJoCo viewer.

      .. tab-item:: Real Robot

         .. warning::

            Before operating on real hardware:

            #. Ensure the working area is free of any persons or other potential hazards.
            #. Always start with ``blend_ratio`` at ``0.0``. You can increase from ``0.0`` to ``1.0`` in a single step since the ratio is smoothed internally.
            #. Ensure the waist yaw joint is close to zero before launching. It is uncontrolled and will be held at its current position, so a rotated torso can degrade balance.
            #. Have the disable command ready (refer to the **disable** step below).

         #. **Set up the network** — clone ``isaac_ros_robots`` and run the setup script **outside** the docker container on the host machine:

            .. code-block:: bash

               cd ${ISAAC_ROS_WS}/src && \
                  git clone https://github.com/NVIDIA-ISAAC-ROS/isaac_ros_robots.git

            Run the network setup script:

            .. code-block:: bash

               ${ISAAC_ROS_WS}/src/isaac_ros_robots/isaac_ros_robots_tools/scripts/setup_network.py

            The script will interactively guide you through the network setup. Make sure to select
            the network interface that is physically connected to the H2 robot.

         #. **Launch the application**:

            .. code-block:: bash

               ros2 launch isaac_ros_unitree_h2_teleop_bringup unitree_h2_teleop.launch.py \
                   hardware_type:=real \
                   input_mode:=teleop \
                   network_interface:=<your_interface>

            Replace ``<your_interface>`` with the network interface you selected in the previous step.

            .. note::

               The application starts but the robot will not move because ``blend_ratio`` defaults
               to ``0.0`` on real hardware.

            .. tip::

               To verify that XR commands are reaching the controller:

               .. code-block:: bash

                  ros2 topic echo /xr_teleop/ee_poses
                  ros2 topic echo /xr_teleop/root_twist

         #. **To disable the robot**, set the blend ratio back to zero:

            .. code-block:: bash

               ros2 param set /safety_controller blend_ratio 0.0

            .. tip::

               Keep this command in your shell history so you can execute it quickly if something
               goes wrong.

         #. **Enable the robot** by setting the blend ratio:

            .. code-block:: bash

               ros2 param set /safety_controller blend_ratio 1.0

            The robot will start tracking your hand movements.

            .. note::

               After several minutes of operation, the H2 hands may lower due to
               temperature limits. Allow the robot to cool down before resuming.

Controller Reference
^^^^^^^^^^^^^^^^^^^^

The PICO 4 Ultra headset and Meta Quest 3 include two handheld controllers.
The following table summarizes what each input does during teleoperation:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Input
     - Action
   * - **Left joystick**
     - Move the robot: up = forward, down = backward, left = strafe left, right = strafe right
   * - **Right joystick** — left / right
     - Rotate the robot in place (yaw)
   * - **Controller motion (6-DOF)**
     - The end-effector pose tracks the physical controller; moving and rotating the
       controller moves the robot's hand correspondingly
   * - **Triggers** (each controller has two)
     - Open and close the finger joints of the tri-finger hand

Manus Gloves
^^^^^^^^^^^^

Install Manus plugin:

.. code-block:: bash

   ${ISAAC_ROS_WS}/../lib/src/IsaacTeleop/src/plugins/manus/install_manus.sh

For the first time running this, you also need to setup udev rules on the host (i.e. outside of the
Isaac ROS container).  Just cd into your IsaacTeleop checkout and run:

.. code-block:: bash

   cd ${ISAAC_ROS_WS}/../lib/src/IsaacTeleop

   ./src/plugins/manus/install_udev_rules.sh

Then follow :ref:`Running the Manus plugin <running-the-manus-plugin>` to verify the Manus SDK is
properly connected and learn how to run the Manus plugin.

API
---

Usage
^^^^^

.. code:: bash

   ros2 launch isaac_ros_unitree_h2_teleop_bringup unitree_h2_teleop.launch.py

Launch Arguments
^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Launch Argument
     - Type
     - Default
     - Description
   * - ``hardware_type``
     - ``string``
     - ``mujoco``
     - Hardware platform. Options: ``mujoco`` (simulation), ``real`` (physical robot).
   * - ``input_mode``
     - ``string``
     - ``teleop``
     - Input source. Options: ``teleop`` (XR device via CloudXR), ``markers`` (RViz interactive markers).
   * - ``network_interface``
     - ``string``
     - ``eno1``
     - Network interface for H2 communication. Only used when ``hardware_type:=real``.
   * - ``enable_viewer``
     - ``bool``
     - ``true``
     - Enable MuJoCo GUI viewer. Only used when ``hardware_type:=mujoco``.
   * - ``use_rviz``
     - ``bool``
     - ``false``
     - Enable RViz visualization. Automatically set to ``true`` when ``input_mode:=markers``.
   * - ``use_foxglove``
     - ``bool``
     - ``false``
     - Start Foxglove bridge for remote monitoring.

ROS Topics
^^^^^^^^^^

Topics depend on the ``input_mode`` launch argument. In ``teleop`` mode:

.. list-table::
   :header-rows: 1

   * - ROS Topic
     - Interface
     - Description
   * - ``/xr_teleop/ee_poses``
     - ``geometry_msgs/PoseArray``
     - End-effector (wrist) poses from XR headset
   * - ``/xr_teleop/root_twist``
     - ``geometry_msgs/TwistStamped``
     - Root velocity command from XR headset
   * - ``/xr_teleop/finger_joints``
     - ``sensor_msgs/JointState``
     - Retargeted finger joint angles from XR hand tracking

   * - ``/xr_teleop/controller_data``
     - ``std_msgs/ByteMultiArray``
     - Raw controller state encoded as msgpack (button, trigger, thumbstick, and pose data)

In ``markers`` mode:

.. list-table::
   :header-rows: 1

   * - ROS Topic
     - Interface
     - Description
   * - ``/ik_controller/reference_pose``
     - ``geometry_msgs/PoseArray``
     - End-effector poses published by the RViz interactive marker node

ROS Parameters
^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Parameter
     - Node
     - Type
     - Default
     - Description
   * - ``blend_ratio``
     - ``/safety_controller``
     - ``double``
     - ``0.0`` (real), ``1.0`` (sim)
     - Policy activation level (0.0–1.0). Dynamically adjustable at runtime.

Troubleshooting
---------------

Test Without an XR Headset (Interactive Markers Mode)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If the XR headset is unavailable or you want to isolate whether an issue is
with XR or the robot itself, launch with ``input_mode:=markers``:

.. code-block:: bash

   ros2 launch isaac_ros_unitree_h2_teleop_bringup unitree_h2_teleop.launch.py \
       input_mode:=markers

RViz opens automatically with 6-DOF interactive markers for each wrist.
The ``/ik_controller/reference_pose`` topic
replaces the ``/xr_teleop/ee_poses`` topic in this mode.

#. Publish to ``/cmd_vel`` to start the controller:

   .. code-block:: bash

      ros2 topic pub --rate 10 /cmd_vel geometry_msgs/msg/Twist \
          "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"

#. In the RViz **Displays** panel, find the **IK Target Marker** display and set
   its **Interactive Markers Namespace** to ``/ik_controller_marker``. You can
   then drag the wrist markers to command the arms.

Remote Monitoring with Foxglove
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If visualization via Foxglove is desired, add
``use_foxglove:=true`` to any launch command to start the Foxglove bridge:

.. code-block:: bash

   ros2 launch isaac_ros_unitree_h2_teleop_bringup unitree_h2_teleop.launch.py \
       use_foxglove:=true

Refer to the `Foxglove Studio documentation <https://foxglove.dev/docs/studio>`__ for
instructions on connecting Foxglove Studio.

.. |package_name| replace:: ``isaac_ros_unitree_h2_teleop_bringup``
