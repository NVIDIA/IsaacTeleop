# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Hands Source - DeviceIO Hand Tracker integration.

Provides left and right hand tracking data from DeviceIO's HandTracker.
"""

import numpy as np
from typing import TYPE_CHECKING
from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HandInput, NUM_HAND_JOINTS

if TYPE_CHECKING:
    from teleopcore.deviceio import HandTracker, DeviceIOSession
    from teleopcore.schema import HandPoseT


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

        # Create source module (requires session for data retrieval)
        hands = HandsSource(hand_tracker, session, name="hands")

        # Use in retargeting graph
        retargeter = MyHandRetargeter(name="my_hand_retargeter")
        connected = retargeter.connect({
            "hand_left": hands.output("hand_left"),
            "hand_right": hands.output("hand_right")
        })
    """

    def __init__(self, hand_tracker: "HandTracker", session: "DeviceIOSession", name: str) -> None:
        """
        Initialize hands source with existing HandTracker and session.

        Args:
            hand_tracker: teleopcore.deviceio.HandTracker instance
            session: teleopcore.deviceio.DeviceIOSession instance (needed to get hand data)
            name: Name identifier for this source (must be unique)
        """
        # Store tracker and session references
        self._hand_tracker = hand_tracker
        self._session = session

        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        """Hands source has no inputs."""
        return {}

    def output_spec(self) -> RetargeterIOType:
        """Define hand output collections using standard types."""
        return {
            "hand_left": HandInput(),
            "hand_right": HandInput()
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Read hand tracking data from DeviceIO tracker.

        Args:
            inputs: Empty dict (source modules have no inputs)
            outputs: Dict with "hand_left" and "hand_right" TensorGroups
        """
        # Get hand data from tracker
        left_data = self._hand_tracker.get_left_hand(self._session)
        right_data = self._hand_tracker.get_right_hand(self._session)

        # Update left hand
        self._update_hand_data(outputs["hand_left"], left_data)

        # Update right hand
        self._update_hand_data(outputs["hand_right"], right_data)

    def _update_hand_data(self, group: TensorGroup, hand_data: "HandPoseT") -> None:
        """Helper to update hand data for a single hand."""
        # Pre-allocate arrays
        positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
        orientations = np.zeros((NUM_HAND_JOINTS, 4), dtype=np.float32)
        radii = np.zeros(NUM_HAND_JOINTS, dtype=np.float32)
        valid = np.zeros(NUM_HAND_JOINTS, dtype=np.uint8)  # bool as uint8

        # Extract joint data from HandJoints struct
        joints = hand_data.joints
        for i in range(NUM_HAND_JOINTS):
            joint = joints[i]
            # Access pose through joint.pose
            positions[i] = [joint.pose.position.x, joint.pose.position.y, joint.pose.position.z]
            orientations[i] = [joint.pose.orientation.x, joint.pose.orientation.y, 
                              joint.pose.orientation.z, joint.pose.orientation.w]
            radii[i] = joint.radius
            valid[i] = 1 if joint.is_valid else 0

        # Update tensor group using index-based access
        group[0] = positions      # joint_positions
        group[1] = orientations   # joint_orientations
        group[2] = radii          # joint_radii
        group[3] = valid          # joint_valid
        group[4] = hand_data.is_active
        # Extract timestamp from Timestamp struct
        group[5] = int(hand_data.timestamp.device_time)
