# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Hands Source Node - DeviceIO to Retargeting Engine converter.

Converts raw HandPoseT flatbuffer data to standard HandInput tensor format.
"""

import numpy as np
from typing import TYPE_CHECKING
from ..interface.base_retargeter import BaseRetargeter
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HandInput, NUM_HAND_JOINTS
from .deviceio_tensor_types import DeviceIOHandPose

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import HandPoseT


class HandsSource(BaseRetargeter, IDeviceIOSource):
    """
    Stateless converter: DeviceIO HandPoseT → HandInput tensors.

    Inputs:
        - "deviceio_hand_left": Raw HandPoseT flatbuffer for left hand
        - "deviceio_hand_right": Raw HandPoseT flatbuffer for right hand

    Outputs:
        - "hand_left": Standard HandInput tensor
        - "hand_right": Standard HandInput tensor

    Usage:
        # In TeleopSession, manually poll tracker and pass data
        left_data = hand_tracker.get_left_hand(session)
        right_data = hand_tracker.get_right_hand(session)
        result = hands_source_node({
            "deviceio_hand_left": left_data,
            "deviceio_hand_right": right_data
        })
    """

    LEFT = "hand_left"
    RIGHT = "hand_right"

    def __init__(self, name: str) -> None:
        """Initialize stateless hands source node.

        Creates a HandTracker instance for TeleopSession to discover and use.

        Args:
            name: Unique name for this source node
        """
        import isaacteleop.deviceio as deviceio
        self._hand_tracker = deviceio.HandTracker()
        super().__init__(name)

    @property
    def name(self) -> str:
        """Get the name of this source node."""
        return self._name

    def get_tracker(self) -> "ITracker":
        """Get the HandTracker instance.

        Returns:
            The HandTracker instance for TeleopSession to initialize
        """
        return self._hand_tracker

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO hand inputs."""
        return {
            "deviceio_hand_left": DeviceIOHandPose(),
            "deviceio_hand_right": DeviceIOHandPose()
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard hand input outputs."""
        return {
            "hand_left": HandInput(),
            "hand_right": HandInput()
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Convert DeviceIO HandPoseT to standard HandInput tensors.

        Args:
            inputs: Dict with "deviceio_hand_left" and "deviceio_hand_right" flatbuffer objects
            outputs: Dict with "hand_left" and "hand_right" TensorGroups
        """
        # Extract raw DeviceIO objects
        left_data: "HandPoseT" = inputs["deviceio_hand_left"][0]
        right_data: "HandPoseT" = inputs["deviceio_hand_right"][0]

        # Convert left hand
        self._update_hand_data(outputs["hand_left"], left_data)

        # Convert right hand
        self._update_hand_data(outputs["hand_right"], right_data)

    def _update_hand_data(self, group: TensorGroup, hand_data: "HandPoseT") -> None:
        """Helper to convert hand data for a single hand."""
        # Pre-allocate arrays
        positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
        orientations = np.zeros((NUM_HAND_JOINTS, 4), dtype=np.float32)
        radii = np.zeros(NUM_HAND_JOINTS, dtype=np.float32)
        valid = np.zeros(NUM_HAND_JOINTS, dtype=np.uint8)

        # Extract joint data from HandJoints struct
        joints = hand_data.joints
        for i in range(NUM_HAND_JOINTS):
            joint = joints[i]
            positions[i] = [joint.pose.position.x, joint.pose.position.y, joint.pose.position.z]
            orientations[i] = [joint.pose.orientation.x, joint.pose.orientation.y,
                              joint.pose.orientation.z, joint.pose.orientation.w]
            radii[i] = joint.radius
            valid[i] = 1 if joint.is_valid else 0

        # Update output tensor group
        group[0] = positions
        group[1] = orientations
        group[2] = radii
        group[3] = valid
        group[4] = hand_data.is_active
        group[5] = int(hand_data.timestamp.device_time)
