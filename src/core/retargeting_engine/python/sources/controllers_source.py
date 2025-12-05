# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Controllers Source - DeviceIO Controller Tracker integration.

Provides left and right controller data from DeviceIO's ControllerTracker.
"""

import numpy as np
from typing import Dict, Any, List
from ..interface.retargeting_module import BaseRetargeter, RetargeterIO
from ..interface.tensor_group import TensorGroup
from ..tensor_types import ControllerInput


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
        
        # Create source module
        controllers = ControllersSource(controller_tracker, name="controllers")
        
        # Use in retargeting graph
        gripper = GripperRetargeter(name="gripper")
        connected = gripper.connect({
            "controller_left": controllers.output("controller_left"),
            "controller_right": controllers.output("controller_right")
        })
    """
    
    def __init__(self, controller_tracker: Any, name: str) -> None:
        """
        Initialize controllers source with existing ControllerTracker.
        
        Args:
            controller_tracker: deviceio.ControllerTracker instance
            name: Name identifier for this source (must be unique)
        """
        # Import DeviceIO
        import teleopcore.deviceio as deviceio
        
        # Store Hand enum for later use
        self._hand_left = deviceio.Hand.Left
        self._hand_right = deviceio.Hand.Right
        self._deviceio = deviceio
        
        # Store tracker reference
        self._controller_tracker = controller_tracker
        
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        """Controllers source has no inputs."""
        return {}
    
    def output_spec(self) -> RetargeterIO:
        """Define controller output collections using standard types."""
        return {
            "controller_left": ControllerInput(),
            "controller_right": ControllerInput()
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Read controller tracking data from DeviceIO tracker.
        
        Args:
            inputs: Empty dict (source modules have no inputs)
            outputs: Dict with "controller_left" and "controller_right" TensorGroups
        """
        # Get snapshots from tracker
        left_snapshot = self._controller_tracker.get_snapshot(self._hand_left)
        right_snapshot = self._controller_tracker.get_snapshot(self._hand_right)
        
        # Update left controller
        self._update_controller_data(outputs["controller_left"], left_snapshot)
        
        # Update right controller
        self._update_controller_data(outputs["controller_right"], right_snapshot)
    
    def _update_controller_data(self, group: TensorGroup, snapshot: Any) -> None:
        """Helper to update controller data for a single controller."""
        # Extract pose data as numpy arrays
        grip_pos = np.array(snapshot.grip_pose.position, dtype=np.float32)
        grip_ori = np.array(snapshot.grip_pose.orientation, dtype=np.float32)
        aim_pos = np.array(snapshot.aim_pose.position, dtype=np.float32)
        aim_ori = np.array(snapshot.aim_pose.orientation, dtype=np.float32)
        
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

