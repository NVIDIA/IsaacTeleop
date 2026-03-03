Retargeting Interface
=====================

Isaac Teleop uses a graph-based retargeting pipeline. Data flows from **source nodes** through
**retargeters** and is combined into a single action tensor.

Source Nodes
------------

* ``HandsSource`` -- provides hand tracking data (left/right, 26 joints each).
* ``ControllersSource`` -- provides motion controller data (grip pose, trigger, thumbstick, etc.).

Available Retargeters
---------------------

.. dropdown:: Se3AbsRetargeter / Se3RelRetargeter

   Maps hand or controller tracking to end-effector pose. ``Se3AbsRetargeter`` outputs a 7D
   absolute pose (position + quaternion). ``Se3RelRetargeter`` outputs a 6D delta.
   Configurable rotation offsets (roll, pitch, yaw in degrees).

.. dropdown:: GripperRetargeter

   Outputs a single float (-1.0 closed, 1.0 open). Uses controller trigger (priority) or
   thumb-index pinch distance from hand tracking.

.. dropdown:: DexHandRetargeter / DexBiManualRetargeter

   Retargets full hand tracking (26 joints) to robot-specific hand joint angles using the
   ``dex-retargeting`` library. Requires a robot hand URDF and a YAML configuration file.

   .. warning::

      The links used for retargeting must be defined at the actual fingertips, not in the middle
      of the fingers, to ensure accurate optimization.

.. dropdown:: TriHandMotionControllerRetargeter

   Maps VR controller buttons (trigger, squeeze) to G1 TriHand joints (7 DOF per hand). Simple
   mapping: trigger controls the index finger, squeeze controls the middle finger, and both
   together control the thumb.

.. dropdown:: LocomotionRootCmdRetargeter

   Maps controller thumbsticks to a 4D locomotion command:
   ``[vel_x, vel_y, rot_vel_z, hip_height]``.

.. dropdown:: TensorReorderer

   Utility that flattens and reorders outputs from multiple retargeters into a single 1D action
   tensor. The ``output_order`` must match the action space expected by the environment.


.. _isaac-teleop-pipeline-builder:

Build a Retargeting Pipeline
----------------------------

A pipeline builder is a callable that constructs the retargeting graph and returns an
``OutputCombiner`` with a single ``"action"`` key. Here is a complete example for a Franka
manipulator (from ``stack_ik_abs_env_cfg.py``):

.. code-block:: python
   :class: code-100col

   from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource, HandsSource
   from isaacteleop.retargeting_engine.interface import OutputCombiner, ValueInput
   from isaacteleop.retargeting_engine.retargeters import (
       GripperRetargeter, GripperRetargeterConfig,
       Se3AbsRetargeter, Se3RetargeterConfig,
       TensorReorderer,
   )
   from isaacteleop.retargeting_engine.tensor_types import TransformMatrix

   def build_franka_stack_pipeline():

       # 1. Create input sources
       controllers = ControllersSource(name="controllers")
       hands = HandsSource(name="hands")

       # 2. Apply coordinate-frame transform (world_T_anchor provided by IsaacTeleopDevice)
       transform_input = ValueInput("world_T_anchor", TransformMatrix())
       transformed_controllers = controllers.transformed(
           transform_input.output(ValueInput.VALUE)
       )

       # 3. Create and connect retargeters
       se3_cfg = Se3RetargeterConfig(
           input_device=ControllersSource.RIGHT,
           target_offset_roll=90.0,
       )
       se3 = Se3AbsRetargeter(se3_cfg, name="ee_pose")
       connected_se3 = se3.connect({
           ControllersSource.RIGHT: transformed_controllers.output(ControllersSource.RIGHT),
       })

       gripper_cfg = GripperRetargeterConfig(hand_side="right")
       gripper = GripperRetargeter(gripper_cfg, name="gripper")
       connected_gripper = gripper.connect({
           ControllersSource.RIGHT: transformed_controllers.output(ControllersSource.RIGHT),
           HandsSource.RIGHT: hands.output(HandsSource.RIGHT),
       })

       # 4. Flatten into a single action tensor with TensorReorderer
       ee_elements = ["pos_x", "pos_y", "pos_z", "quat_x", "quat_y", "quat_z", "quat_w"]
       reorderer = TensorReorderer(
           input_config={
               "ee_pose": ee_elements,
               "gripper_command": ["gripper_value"],
           },
           output_order=ee_elements + ["gripper_value"],
           name="action_reorderer",
           input_types={"ee_pose": "array", "gripper_command": "scalar"},
       )
       connected_reorderer = reorderer.connect({
           "ee_pose": connected_se3.output("ee_pose"),
           "gripper_command": connected_gripper.output("gripper_command"),
       })

       # 5. Return OutputCombiner with "action" key
       return OutputCombiner({"action": connected_reorderer.output("output")})

.. tip::

   The ``output_order`` of the ``TensorReorderer`` must match the action space of your environment.
   Mismatches will cause silent control errors.

.. _isaac-teleop-new-retargeter:

Add a New Retargeter
--------------------

If the built-in retargeters do not cover your use case, you can implement a custom one in the
`Isaac Teleop repository <https://github.com/NVIDIA/IsaacTeleop>`_:

#. Inherit from ``BaseRetargeter`` and implement ``input_spec()``, ``output_spec()``, and
   ``compute()``.
#. Optionally add a ``ParameterState`` for parameters that should be live-tunable via the
   retargeter tuning UI.
#. Connect to existing source nodes (``HandsSource``, ``ControllersSource``) or create a new
   ``IDeviceIOSource`` subclass for custom input devices.

See the `Retargeting Engine README <https://github.com/NVIDIA/IsaacTeleop/blob/main/src/core/retargeting_engine/python/retargeters/README.md>`_
and :doc:`Contributing Guide <../getting_started/contributing>` for details.
