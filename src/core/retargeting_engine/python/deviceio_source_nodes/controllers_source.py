# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Controllers Source Node - DeviceIO to Retargeting Engine converter.

Converts raw ControllerSnapshot flatbuffer data to standard ControllerInput tensor format.
"""

import numpy as np
from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import OutputSelector, RetargeterIO, RetargeterIOType
from ..interface.retargeter_subgraph import RetargeterSubgraph
from ..interface.tensor_group import TensorGroup
from ..tensor_types import ControllerInput
from .deviceio_tensor_types import DeviceIOControllerSnapshot

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import ControllerSnapshot


class ControllersSource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO ControllerSnapshot → ControllerInput tensors.

    Inputs:
        - "deviceio_controller_left": Raw ControllerSnapshot flatbuffer for left controller
        - "deviceio_controller_right": Raw ControllerSnapshot flatbuffer for right controller

    Outputs:
        - "controller_left": Standard ControllerInput tensor
        - "controller_right": Standard ControllerInput tensor

    Usage:
        # In TeleopSession, manually poll tracker and pass data
        controller_data = controller_tracker.get_controller_data(session)
        result = controllers_source_node({
            "deviceio_controller_left": controller_data.left_controller,
            "deviceio_controller_right": controller_data.right_controller
        })
    """

    LEFT = "controller_left"
    RIGHT = "controller_right"

    def __init__(self, name: str) -> None:
        """Initialize stateless controllers source node.

        Creates a ControllerTracker instance for TeleopSession to discover and use.

        Args:
            name: Unique name for this source node
        """
        import isaacteleop.deviceio as deviceio
        self._controller_tracker = deviceio.ControllerTracker()
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        """Get the ControllerTracker instance.

        Returns:
            The ControllerTracker instance for TeleopSession to initialize
        """
        return self._controller_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll controller tracker and return input data.

        Args:
            deviceio_session: The active DeviceIO session.

        Returns:
            Dict with "deviceio_controller_left" and "deviceio_controller_right"
            TensorGroups containing raw ControllerSnapshot data.
        """
        controller_data = self._controller_tracker.get_controller_data(deviceio_session)
        source_inputs = self.input_spec()
        result = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            if "left" in input_name:
                tg[0] = controller_data.left_controller
            elif "right" in input_name:
                tg[0] = controller_data.right_controller
            result[input_name] = tg
        return result

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO controller inputs."""
        return {
            "deviceio_controller_left": DeviceIOControllerSnapshot(),
            "deviceio_controller_right": DeviceIOControllerSnapshot()
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard controller input outputs."""
        return {
            "controller_left": ControllerInput(),
            "controller_right": ControllerInput()
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Convert DeviceIO ControllerSnapshot to standard ControllerInput tensors.

        Args:
            inputs: Dict with "deviceio_controller_left" and "deviceio_controller_right" flatbuffer objects
            outputs: Dict with "controller_left" and "controller_right" TensorGroups
        """
        # Extract raw DeviceIO objects
        left_snapshot: "ControllerSnapshot" = inputs["deviceio_controller_left"][0]
        right_snapshot: "ControllerSnapshot" = inputs["deviceio_controller_right"][0]

        # Convert left controller
        self._update_controller_data(outputs["controller_left"], left_snapshot)

        # Convert right controller
        self._update_controller_data(outputs["controller_right"], right_snapshot)

    def _update_controller_data(self, group: TensorGroup, snapshot: "ControllerSnapshot") -> None:
        """Helper to convert controller data for a single controller."""
        # Extract grip pose
        grip_position = np.array([
            snapshot.grip_pose.pose.position.x,
            snapshot.grip_pose.pose.position.y,
            snapshot.grip_pose.pose.position.z
        ], dtype=np.float32)

        grip_orientation = np.array([
            snapshot.grip_pose.pose.orientation.x,
            snapshot.grip_pose.pose.orientation.y,
            snapshot.grip_pose.pose.orientation.z,
            snapshot.grip_pose.pose.orientation.w
        ], dtype=np.float32)

        # Extract aim pose
        aim_position = np.array([
            snapshot.aim_pose.pose.position.x,
            snapshot.aim_pose.pose.position.y,
            snapshot.aim_pose.pose.position.z
        ], dtype=np.float32)

        aim_orientation = np.array([
            snapshot.aim_pose.pose.orientation.x,
            snapshot.aim_pose.pose.orientation.y,
            snapshot.aim_pose.pose.orientation.z,
            snapshot.aim_pose.pose.orientation.w
        ], dtype=np.float32)

        # Update output tensor group
        group[0] = grip_position
        group[1] = grip_orientation
        group[2] = aim_position
        group[3] = aim_orientation
        group[4] = float(snapshot.inputs.primary_click)
        group[5] = float(snapshot.inputs.secondary_click)
        group[6] = float(snapshot.inputs.thumbstick_click)
        group[7] = float(snapshot.inputs.thumbstick_x)
        group[8] = float(snapshot.inputs.thumbstick_y)
        group[9] = float(snapshot.inputs.squeeze_value)
        group[10] = float(snapshot.inputs.trigger_value)
        group[11] = snapshot.is_active  # BoolType, don't convert

    def transformed(self, transform_input: OutputSelector) -> RetargeterSubgraph:
        """
        Create a subgraph that applies a 4x4 transform to controller poses.

        This is a convenience method equivalent to manually creating a
        ControllerTransform node and connecting it.

        Args:
            transform_input: An OutputSelector providing a TransformMatrix
                (e.g., value_input.output("value")).

        Returns:
            A RetargeterSubgraph with outputs "controller_left" and "controller_right"
            containing the transformed ControllerInput data.

        Example:
            ctrl_source = ControllersSource("controllers")
            xform_input = ValueInput("xform", TransformMatrix())
            transformed = ctrl_source.transformed(xform_input.output("value"))
        """
        from ..utilities.controller_transform import ControllerTransform

        xform_node = ControllerTransform(f"{self.name}_transform")
        return xform_node.connect({
            self.LEFT: self.output(self.LEFT),
            self.RIGHT: self.output(self.RIGHT),
            "transform": transform_input,
        })
