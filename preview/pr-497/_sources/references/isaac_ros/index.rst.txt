Isaac ROS Integrations
======================

Isaac Teleop integrates with `Isaac ROS <https://nvidia-isaac-ros.github.io>`__
to drive supported humanoid robots end-to-end: XR input is captured by the Isaac
Teleop server and forwarded into ROS 2 launch files that combine AGILE locomotion,
bimanual inverse kinematics, and finger control on the target platform.

The bringup packages below are the per-robot entry points for running teleoperation
on both MuJoCo simulation and real hardware.

.. toctree::
   :maxdepth: 1
   :caption: Robot bringup

   unitree_h2/index
