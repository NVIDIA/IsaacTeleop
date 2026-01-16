# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Head Source Node - DeviceIO to Retargeting Engine converter.

Converts raw HeadPoseT flatbuffer data to standard HeadPose tensor format.
"""

import numpy as np
from typing import TYPE_CHECKING
from ..interface.base_retargeter import BaseRetargeter
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HeadPose
from .deviceio_tensor_types import DeviceIOHeadPose

if TYPE_CHECKING:
    from teleopcore.deviceio import ITracker
    from teleopcore.schema import HeadPoseT


class HeadSource(BaseRetargeter, IDeviceIOSource):
    """
    Stateless converter: DeviceIO HeadPoseT → HeadPose tensor.

    Inputs:
        - "deviceio_head": Raw HeadPoseT flatbuffer object from DeviceIO
    
    Outputs:
        - "head": Standard HeadPose tensor (position, orientation, is_valid, timestamp)
    
    Usage:
        # In TeleopSession, manually poll tracker and pass data
        head_data = head_tracker.get_head(session)
        result = head_source_node({"deviceio_head": head_data})
    """

    def __init__(self, name: str) -> None:
        """Initialize stateless head source node.
        
        Creates a HeadTracker instance for TeleopSession to discover and use.
        
        Args:
            name: Unique name for this source node
        """
        import teleopcore.deviceio as deviceio
        self._head_tracker = deviceio.HeadTracker()
        super().__init__(name)
    
    @property
    def name(self) -> str:
        """Get the name of this source node."""
        return self._name
    
    def get_tracker(self) -> "ITracker":
        """Get the HeadTracker instance.
        
        Returns:
            The HeadTracker instance for TeleopSession to initialize
        """
        return self._head_tracker

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO head input."""
        return {
            "deviceio_head": DeviceIOHeadPose()
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard head pose output."""
        return {
            "head": HeadPose()
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Convert DeviceIO HeadPoseT to standard HeadPose tensor.

        Args:
            inputs: Dict with "deviceio_head" containing HeadPoseT flatbuffer object
            outputs: Dict with "head" TensorGroup
        """
        # Extract the raw DeviceIO object
        head_pose: "HeadPoseT" = inputs["deviceio_head"][0]

        # Convert to numpy arrays
        position = np.array([
            head_pose.pose.position.x,
            head_pose.pose.position.y,
            head_pose.pose.position.z
        ], dtype=np.float32)
        
        orientation = np.array([
            head_pose.pose.orientation.x,
            head_pose.pose.orientation.y,
            head_pose.pose.orientation.z,
            head_pose.pose.orientation.w
        ], dtype=np.float32)

        # Update output tensor group
        output = outputs["head"]
        output[0] = position
        output[1] = orientation
        output[2] = head_pose.is_valid
        output[3] = int(head_pose.timestamp.device_time)
