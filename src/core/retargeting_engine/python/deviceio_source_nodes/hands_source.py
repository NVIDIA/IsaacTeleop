# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Hands Source Node - DeviceIO to Retargeting Engine converter.

Converts raw HandPoseT flatbuffer data to standard HandInput tensor format.
"""

import numpy as np
from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import (
    OutputSelector,
    RetargeterIO,
    RetargeterIOType,
)
from ..interface.retargeter_subgraph import RetargeterSubgraph
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HandInput, NUM_HAND_JOINTS
from .deviceio_tensor_types import DeviceIOHandPose

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import HandPoseT


class HandsSource(IDeviceIOSource):
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

    def get_tracker(self) -> "ITracker":
        """Get the HandTracker instance.

        Returns:
            The HandTracker instance for TeleopSession to initialize
        """
        return self._hand_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll hand tracker and return input data.

        Args:
            deviceio_session: The active DeviceIO session.

        Returns:
            Dict with "deviceio_hand_left" and "deviceio_hand_right" TensorGroups
            containing raw HandPoseT data.
        """
        left_hand = self._hand_tracker.get_left_hand(deviceio_session)
        right_hand = self._hand_tracker.get_right_hand(deviceio_session)
        source_inputs = self.input_spec()
        result = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            if "left" in input_name:
                tg[0] = left_hand
            elif "right" in input_name:
                tg[0] = right_hand
            result[input_name] = tg
        return result

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO hand inputs."""
        return {
            "deviceio_hand_left": DeviceIOHandPose(),
            "deviceio_hand_right": DeviceIOHandPose(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard hand input outputs."""
        return {"hand_left": HandInput(), "hand_right": HandInput()}

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
            positions[i] = [
                joint.pose.position.x,
                joint.pose.position.y,
                joint.pose.position.z,
            ]
            orientations[i] = [
                joint.pose.orientation.x,
                joint.pose.orientation.y,
                joint.pose.orientation.z,
                joint.pose.orientation.w,
            ]
            radii[i] = joint.radius
            valid[i] = 1 if joint.is_valid else 0

        # Update output tensor group
        group[0] = positions
        group[1] = orientations
        group[2] = radii
        group[3] = valid
        group[4] = hand_data.is_active

    def transformed(self, transform_input: OutputSelector) -> RetargeterSubgraph:
        """
        Create a subgraph that applies a 4x4 transform to all hand joint poses.

        This is a convenience method equivalent to manually creating a HandTransform
        node and connecting it.

        Args:
            transform_input: An OutputSelector providing a TransformMatrix
                (e.g., value_input.output("value")).

        Returns:
            A RetargeterSubgraph with outputs "hand_left" and "hand_right"
            containing the transformed HandInput data.

        Example:
            hand_source = HandsSource("hands")
            xform_input = ValueInput("xform", TransformMatrix())
            transformed = hand_source.transformed(xform_input.output("value"))
        """
        from ..utilities.hand_transform import HandTransform

        xform_node = HandTransform(f"{self.name}_transform")
        return xform_node.connect(
            {
                self.LEFT: self.output(self.LEFT),
                self.RIGHT: self.output(self.RIGHT),
                "transform": transform_input,
            }
        )
