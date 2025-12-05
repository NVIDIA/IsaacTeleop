# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Head Source - DeviceIO Head Tracker integration.

Provides head tracking data from DeviceIO's HeadTracker.
"""

import numpy as np
from typing import Dict, Any
from ..interface.retargeting_module import BaseRetargeter, RetargeterIO
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HeadPose


class HeadSource(BaseRetargeter):
    """
    Source module that reads head tracking data from DeviceIO HeadTracker.
    
    Outputs:
        - "head": Head pose data
    
    This is a source module (no inputs) that wraps DeviceIO's HeadTracker
    and provides head data in the standard format.
    
    Usage:
        import teleopcore.deviceio as deviceio
        
        # Create tracker
        head_tracker = deviceio.HeadTracker()
        
        # Create source module
        head = HeadSource(head_tracker, name="head")
        
        # Use in retargeting graph
        retargeter = MyHeadRetargeter(name="my_head_retargeter")
        connected = retargeter.connect({
            "head": head.output("head")
        })
    """
    
    def __init__(self, head_tracker: Any, name: str) -> None:
        """
        Initialize head source with existing HeadTracker.
        
        Args:
            head_tracker: deviceio.HeadTracker instance
            name: Name identifier for this source (must be unique)
        """
        # Store tracker reference
        self._head_tracker = head_tracker
        
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        """Head source has no inputs."""
        return {}
    
    def output_spec(self) -> RetargeterIO:
        """Define head output collection using standard types."""
        return {
            "head": HeadPose()
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Read head tracking data from DeviceIO tracker.
        
        Args:
            inputs: Empty dict (source modules have no inputs)
            outputs: Dict with "head" TensorGroup
        """
        # Get head pose from tracker
        head_pose = self._head_tracker.get_head()
        
        # Convert to numpy arrays
        position = np.array(head_pose.position, dtype=np.float32)
        orientation = np.array(head_pose.orientation, dtype=np.float32)
        
        # Update tensor group using index-based access
        output = outputs["head"]
        output[0] = position
        output[1] = orientation
        output[2] = head_pose.is_valid
        output[3] = int(head_pose.timestamp)

