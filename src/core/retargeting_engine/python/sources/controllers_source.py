# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Controllers Source - DeviceIO Controller Tracker integration.

Provides left and right controller data from DeviceIO's ControllerTracker.
"""

import numpy as np
from typing import TYPE_CHECKING
from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import ControllerInput

if TYPE_CHECKING:
    from teleopcore.deviceio import ControllerTracker, DeviceIOSession, ControllerSnapshot


class ControllersSource(BaseRetargeter):
    """
    Source module that reads controller data from DeviceIO ControllerTracker.

    Outputs:
        - "controller_left": Left controller state
        - "controller_right": Right controller state

    This is a source module (no inputs) that wraps DeviceIO's ControllerTracker
    and provides controller data in the standard format.

    Usage:
        import teleopcore.deviceio as deviceio

        # Create tracker
        controller_tracker = deviceio.ControllerTracker()

        # Create source module (requires session for data retrieval)
        controllers = ControllersSource(controller_tracker, session, name="controllers")

        # Use in retargeting graph
        gripper = GripperRetargeter(name="gripper")
        connected = gripper.connect({
            "controller_left": controllers.output("controller_left"),
            "controller_right": controllers.output("controller_right")
        })
    """

    def __init__(self, controller_tracker: "ControllerTracker", session: "DeviceIOSession", name: str) -> None:
        """
        Initialize controllers source with existing ControllerTracker and session.

        Args:
            controller_tracker: teleopcore.deviceio.ControllerTracker instance
            session: teleopcore.deviceio.DeviceIOSession instance (needed to get controller data)
            name: Name identifier for this source (must be unique)
        """
        # Store tracker and session references
        self._controller_tracker = controller_tracker
        self._session = session

        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        """Controllers source has no inputs."""
        return {}

    def output_spec(self) -> RetargeterIOType:
        """Define controller output collections using standard types."""
        return {
            "controller_left": ControllerInput(),
            "controller_right": ControllerInput()
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Read controller tracking data from DeviceIO tracker.

        Args:
            inputs: Empty dict (source modules have no inputs)
            outputs: Dict with "controller_left" and "controller_right" TensorGroups
        """
        # Get controller data for both controllers
        controller_data = self._controller_tracker.get_controller_data(self._session)

        # Update left controller
        self._update_controller_data(outputs["controller_left"], controller_data.left_controller)

        # Update right controller
        self._update_controller_data(outputs["controller_right"], controller_data.right_controller)

    def _update_controller_data(self, group: TensorGroup, snapshot: "ControllerSnapshot") -> None:
        """Helper to update controller data for a single controller."""
        # Extract pose data as numpy arrays
        grip_pos = np.array([
            snapshot.grip_pose.pose.position.x,
            snapshot.grip_pose.pose.position.y,
            snapshot.grip_pose.pose.position.z
        ], dtype=np.float32)
        
        grip_ori = np.array([
            snapshot.grip_pose.pose.orientation.x,
            snapshot.grip_pose.pose.orientation.y,
            snapshot.grip_pose.pose.orientation.z,
            snapshot.grip_pose.pose.orientation.w
        ], dtype=np.float32)
        
        aim_pos = np.array([
            snapshot.aim_pose.pose.position.x,
            snapshot.aim_pose.pose.position.y,
            snapshot.aim_pose.pose.position.z
        ], dtype=np.float32)
        
        aim_ori = np.array([
            snapshot.aim_pose.pose.orientation.x,
            snapshot.aim_pose.pose.orientation.y,
            snapshot.aim_pose.pose.orientation.z,
            snapshot.aim_pose.pose.orientation.w
        ], dtype=np.float32)

        # Extract input state
        inputs = snapshot.inputs

        # Update tensor group using index-based access
        # NDArray fields (indices 0-3)
        group[0] = grip_pos    # grip_position
        group[1] = grip_ori    # grip_orientation
        group[2] = aim_pos     # aim_position
        group[3] = aim_ori     # aim_orientation

        # Scalar fields (indices 4-11) - access struct fields directly
        group[4] = float(inputs.primary_click)
        group[5] = float(inputs.secondary_click)
        group[6] = float(inputs.thumbstick_x)
        group[7] = float(inputs.thumbstick_y)
        group[8] = float(inputs.thumbstick_click)
        group[9] = float(inputs.squeeze_value)
        group[10] = float(inputs.trigger_value)
        group[11] = snapshot.is_active
