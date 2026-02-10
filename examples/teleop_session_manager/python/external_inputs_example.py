#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
External Inputs Example with TeleopSessionManager

Demonstrates using TeleopSession with a pipeline that has both DeviceIO sources
(auto-polled from hardware trackers) and external leaf nodes whose inputs are
provided by the caller at each step().

This example shows:
1. Creating a pipeline with mixed DeviceIO and non-DeviceIO leaf nodes
2. Applying a 4x4 coordinate-frame transform to controller data
3. Using get_external_input_specs() to discover required external inputs
4. Passing external inputs (robot EE state + transform matrix) to step()

Scenario:
    A "delta position" retargeter takes two inputs:
    - Controller grip position (from DeviceIO via ControllersSource, transformed)
    - Current robot end-effector position (from the caller / simulator)

    A coordinate-frame transform is applied to the controller data before
    computing the delta, allowing the caller to align the VR tracking frame
    with the robot's world frame.
"""

import sys
import time
import numpy as np
from pathlib import Path
from typing import Dict

from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    OutputCombiner,
    PassthroughInput,
    TensorGroup,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    TransformMatrix,
    NDArrayType,
    DLDataType,
)
from isaacteleop.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig,
    PluginConfig,
)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"


# ==============================================================================
# Custom Tensor Types
# ==============================================================================


def RobotEndEffectorState() -> TensorGroupType:
    """End-effector state provided by the simulator each frame.

    Contains:
        position: (3,) float32 array [x, y, z]
    """
    return TensorGroupType("robot_ee_state", [
        NDArrayType("position", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32),
    ])


def DeltaCommand() -> TensorGroupType:
    """Velocity / delta-position command for the robot.

    Contains:
        delta_position: (3,) float32 array [dx, dy, dz]
    """
    return TensorGroupType("delta_command", [
        NDArrayType("delta_position", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32),
    ])


# ==============================================================================
# External-Input Leaf Node (SimState)
# ==============================================================================


class SimStateSource(BaseRetargeter):
    """Leaf node whose inputs come from the caller (the simulator), not DeviceIO.

    Because this class does NOT implement IDeviceIOSource, TeleopSession treats
    it as an external leaf.  The caller must supply its inputs via step().

    Inputs:
        - "ee_state": RobotEndEffectorState (position of the robot end-effector)

    Outputs:
        - "ee_state": RobotEndEffectorState (passed through unchanged)
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def input_spec(self):
        return {"ee_state": RobotEndEffectorState()}

    def output_spec(self):
        return {"ee_state": RobotEndEffectorState()}

    def compute(self, inputs, outputs):
        # Pass through -- the retargeting engine handles wrapping / unwrapping
        outputs["ee_state"][0] = inputs["ee_state"][0]


# ==============================================================================
# Delta Position Retargeter
# ==============================================================================


class DeltaPositionRetargeter(BaseRetargeter):
    """Computes delta between controller grip position and robot end-effector.

    Inputs:
        - "controller": ControllerInput (from ControllersSource)
        - "ee_state":   RobotEndEffectorState (from SimStateSource)

    Outputs:
        - "delta": DeltaCommand -- (controller_pos - ee_pos)
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def input_spec(self):
        return {
            "controller": ControllerInput(),
            "ee_state": RobotEndEffectorState(),
        }

    def output_spec(self):
        return {
            "delta": DeltaCommand(),
        }

    def compute(self, inputs, outputs):
        # ControllerInput tensor 0 is grip_position (3,)
        grip_pos = np.asarray(inputs["controller"][0], dtype=np.float32)
        ee_pos = np.asarray(inputs["ee_state"][0], dtype=np.float32)
        outputs["delta"][0] = grip_pos - ee_pos


# ==============================================================================
# Main
# ==============================================================================


def main() -> int:
    # ==================================================================
    # 1. Build Pipeline
    # ==================================================================
    #
    # Leaf nodes:
    #   - controllers    (ControllersSource)  -> auto-polled by TeleopSession
    #   - sim_state      (SimStateSource)     -> provided by the caller
    #   - transform_input (PassthroughInput)  -> provided by the caller
    #
    # Graph:
    #   controllers ──> .transformed() ──> delta_left  ──┐
    #   transform_input ──────────────────> delta_left  ──┤
    #   sim_state ────────────────────────> delta_left  ──┤
    #                                                     ├──> OutputCombiner
    #   controllers ──> .transformed() ──> delta_right ──┤
    #   transform_input ──────────────────> delta_right ──┤
    #   sim_state ────────────────────────> delta_right ──┘
    #

    controllers = ControllersSource(name="controllers")
    sim_state = SimStateSource(name="sim_state")

    # Create a PassthroughInput for the coordinate-frame transform.
    # This is an external leaf -- the caller provides the 4x4 matrix each frame.
    transform_input = PassthroughInput("transform_input", TransformMatrix())

    # Apply the transform to controller data before retargeting.
    # .transformed() wires up the internal transform node and returns a subgraph
    # with the same outputs ("controller_left", "controller_right") but in the
    # new coordinate frame.
    transformed_controllers = controllers.transformed(
        transform_input.output(PassthroughInput.VALUE)
    )

    delta_left = DeltaPositionRetargeter(name="delta_left")
    pipeline_left = delta_left.connect({
        "controller": transformed_controllers.output(ControllersSource.LEFT),
        "ee_state": sim_state.output("ee_state"),
    })

    delta_right = DeltaPositionRetargeter(name="delta_right")
    pipeline_right = delta_right.connect({
        "controller": transformed_controllers.output(ControllersSource.RIGHT),
        "ee_state": sim_state.output("ee_state"),
    })

    pipeline = OutputCombiner({
        "delta_left": pipeline_left.output("delta"),
        "delta_right": pipeline_right.output("delta"),
    })

    # ==================================================================
    # 2. Create TeleopSession
    # ==================================================================

    config = TeleopSessionConfig(
        app_name="ExternalInputsExample",
        pipeline=pipeline,
        plugins=[
            PluginConfig(
                plugin_name="controller_synthetic_hands",
                plugin_root_id="synthetic_hands",
                search_paths=[PLUGIN_ROOT_DIR],
            )
        ],
    )

    with TeleopSession(config) as session:
        # ==============================================================
        # 3. Discover what external inputs the pipeline expects
        # ==============================================================
        ext_specs = session.get_external_input_specs()
        print("\n" + "=" * 70)
        print("External Inputs Example (with transform)")
        print("=" * 70)
        print(f"\nPipeline has external inputs: {session.has_external_inputs()}")
        print(f"External leaf nodes and their input specs:")
        for leaf_name, input_spec in ext_specs.items():
            print(f"  - {leaf_name}:")
            for input_name, tensor_group_type in input_spec.items():
                print(f"      {input_name}: {tensor_group_type}")
        print("\nPress Ctrl+C to exit\n")

        # ==============================================================
        # 4. Simulated robot state and coordinate transform
        # ==============================================================
        sim_ee_position = np.array([0.3, 0.0, 0.5], dtype=np.float32)

        # Example: 90-degree rotation about Y to align VR frame with robot frame,
        # plus a 1m translation along Z.
        vr_to_robot = np.array([
            [ 0.0, 0.0, 1.0, 0.0],
            [ 0.0, 1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0, 1.0],
            [ 0.0, 0.0, 0.0, 1.0],
        ], dtype=np.float32)

        # ==============================================================
        # 5. Main loop -- pass external inputs to step()
        # ==============================================================
        while True:
            # Build TensorGroup for the sim_state leaf's "ee_state" input
            ee_input = TensorGroup(RobotEndEffectorState())
            ee_input[0] = sim_ee_position

            # Build TensorGroup for the transform_input leaf's "value" input
            xform_input = TensorGroup(TransformMatrix())
            xform_input[0] = vr_to_robot

            # Call step() with external inputs for the non-DeviceIO leaves
            result = session.step(external_inputs={
                "sim_state": {"ee_state": ee_input},
                "transform_input": {PassthroughInput.VALUE: xform_input},
            })

            # Read outputs
            delta_l = result["delta_left"][0]
            delta_r = result["delta_right"][0]

            if session.frame_count % 30 == 0:
                elapsed = session.get_elapsed_time()
                print(
                    f"[{elapsed:5.1f}s] "
                    f"delta_L=[{delta_l[0]:+.3f}, {delta_l[1]:+.3f}, {delta_l[2]:+.3f}]  "
                    f"delta_R=[{delta_r[0]:+.3f}, {delta_r[1]:+.3f}, {delta_r[2]:+.3f}]"
                )

            # Slowly drift the simulated EE position (pretend robot is moving)
            sim_ee_position += np.array([0.0001, 0.0, 0.0], dtype=np.float32)

            time.sleep(0.016)  # ~60 FPS

    return 0


if __name__ == "__main__":
    sys.exit(main())
