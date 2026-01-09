# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Head Source - DeviceIO Head Tracker integration.

Provides head tracking data from DeviceIO's HeadTracker.
"""

import numpy as np
from typing import TYPE_CHECKING
from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HeadPose

if TYPE_CHECKING:
    from teleopcore.deviceio import HeadTracker, DeviceIOSession
    from teleopcore.schema import HeadPoseT


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

        # Create source module (requires session for data retrieval)
        head = HeadSource(head_tracker, session, name="head")

        # Use in retargeting graph
        retargeter = MyHeadRetargeter(name="my_head_retargeter")
        connected = retargeter.connect({
            "head": head.output("head")
        })
    """

    def __init__(self, head_tracker: "HeadTracker", session: "DeviceIOSession", name: str) -> None:
        """
        Initialize head source with existing HeadTracker and session.

        Args:
            head_tracker: teleopcore.deviceio.HeadTracker instance
            session: teleopcore.deviceio.DeviceIOSession instance (needed to get head data)
            name: Name identifier for this source (must be unique)
        """
        # Store tracker and session references
        self._head_tracker = head_tracker
        self._session = session

        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        """Head source has no inputs."""
        return {}

    def output_spec(self) -> RetargeterIOType:
        """Define head output collection using standard types."""
        return {
            "head": HeadPose()
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Read head tracking data from DeviceIO tracker.

        Args:
            inputs: Empty dict (source modules have no inputs)
            outputs: Dict with "head" TensorGroup
        """
        # Get head pose from tracker
        head_pose: "HeadPoseT" = self._head_tracker.get_head(self._session)

        # Convert to numpy arrays - accessing through .pose
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

        # Update tensor group using index-based access
        output = outputs["head"]
        output[0] = position
        output[1] = orientation
        output[2] = head_pose.is_valid
        # Extract timestamp from Timestamp struct
        output[3] = int(head_pose.timestamp.device_time)
