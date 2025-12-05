# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Hands Source - DeviceIO Hand Tracker integration.

Provides left and right hand tracking data from DeviceIO's HandTracker.
"""

import numpy as np
from typing import Dict, Any
from ..interface.retargeting_module import BaseRetargeter, RetargeterIO
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HandInput, NUM_HAND_JOINTS


class HandsSource(BaseRetargeter):
    """
    Source module that reads hand tracking data from DeviceIO HandTracker.
    
    Outputs:
        - "hand_left": Left hand joint data
        - "hand_right": Right hand joint data
    
    This is a source module (no inputs) that wraps DeviceIO's HandTracker
    and provides hand data in the standard format.
    
    Usage:
        import teleopcore.deviceio as deviceio
        
        # Create tracker
        hand_tracker = deviceio.HandTracker()
        
        # Create source module
        hands = HandsSource(hand_tracker, name="hands")
        
        # Use in retargeting graph
        retargeter = MyHandRetargeter(name="my_hand_retargeter")
        connected = retargeter.connect({
            "hand_left": hands.output("hand_left"),
            "hand_right": hands.output("hand_right")
        })
    """
    
    def __init__(self, hand_tracker: Any, name: str) -> None:
        """
        Initialize hands source with existing HandTracker.
        
        Args:
            hand_tracker: deviceio.HandTracker instance
            name: Name identifier for this source (must be unique)
        """
        # Store tracker reference
        self._hand_tracker = hand_tracker
        
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        """Hands source has no inputs."""
        return {}
    
    def output_spec(self) -> RetargeterIO:
        """Define hand output collections using standard types."""
        return {
            "hand_left": HandInput(),
            "hand_right": HandInput()
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Read hand tracking data from DeviceIO tracker.
        
        Args:
            inputs: Empty dict (source modules have no inputs)
            outputs: Dict with "hand_left" and "hand_right" TensorGroups
        """
        # Get hand data from tracker
        left_data = self._hand_tracker.get_left_hand()
        right_data = self._hand_tracker.get_right_hand()
        
        # Update left hand
        self._update_hand_data(outputs["hand_left"], left_data)
        
        # Update right hand
        self._update_hand_data(outputs["hand_right"], right_data)
    
    def _update_hand_data(self, group: TensorGroup, hand_data: Any) -> None:
        """Helper to update hand data for a single hand."""
        # Pre-allocate arrays
        positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
        orientations = np.zeros((NUM_HAND_JOINTS, 4), dtype=np.float32)
        radii = np.zeros(NUM_HAND_JOINTS, dtype=np.float32)
        valid = np.zeros(NUM_HAND_JOINTS, dtype=np.uint8)  # bool as uint8
        
        # Extract joint data
        for i in range(hand_data.num_joints):
            joint = hand_data.get_joint(i)
            positions[i] = joint.position
            orientations[i] = joint.orientation
            radii[i] = joint.radius
            valid[i] = 1 if joint.is_valid else 0
        
        # Update tensor group using index-based access
        group[0] = positions      # joint_positions
        group[1] = orientations   # joint_orientations
        group[2] = radii          # joint_radii
        group[3] = valid          # joint_valid
        group[4] = hand_data.is_active
        group[5] = int(hand_data.timestamp)

