# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Head Source Node - DeviceIO to Retargeting Engine converter.

Converts raw HeadPoseT flatbuffer data to standard HeadPose tensor format.
"""

import numpy as np
from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import (
    OutputSelector,
    RetargeterIO,
    RetargeterIOType,
)
from ..interface.tensor_group import TensorGroup
from ..interface.tensor_group_type import OptionalType
from ..interface.retargeter_subgraph import RetargeterSubgraph
from ..tensor_types import HeadPose, HeadPoseIndex
from .deviceio_tensor_types import DeviceIOHeadPose

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import HeadPoseT


class HeadSource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO HeadPoseT → HeadPose tensor.

    Inputs:
        - "deviceio_head": Raw HeadPoseT flatbuffer object from DeviceIO

    Outputs (Optional — absent when head tracking is invalid):
        - "head": OptionalTensorGroup (check ``.is_none`` before access)

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
        import isaacteleop.deviceio as deviceio

        self._head_tracker = deviceio.HeadTracker()
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        """Get the HeadTracker instance.

        Returns:
            The HeadTracker instance for TeleopSession to initialize
        """
        return self._head_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll head tracker and return input data.

        Args:
            deviceio_session: The active DeviceIO session.

        Returns:
            Dict with "deviceio_head" TensorGroup containing raw HeadPoseT data.
        """
        head_data = self._head_tracker.get_head(deviceio_session)
        source_inputs = self.input_spec()
        result: RetargeterIO = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            tg[0] = head_data
            result[input_name] = tg
        return result

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO head input."""
        return {"deviceio_head": DeviceIOHeadPose()}

    def output_spec(self) -> RetargeterIOType:
        """Declare standard head pose output (Optional — may be absent)."""
        return {"head": OptionalType(HeadPose())}

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Convert DeviceIO HeadPoseT to standard HeadPose tensor.

        The ``is_valid`` flag is passed through as data — consumers decide
        how to handle invalid poses.  The output is always present; the
        Optional wrapper exists so downstream nodes can accept an absent
        head when no head tracker is connected.

        Args:
            inputs: Dict with "deviceio_head" containing HeadPoseT flatbuffer object
            outputs: Dict with "head" OptionalTensorGroup
        """
        head_pose: "HeadPoseT" = inputs["deviceio_head"][0]

        position = np.array(
            [
                head_pose.pose.position.x,
                head_pose.pose.position.y,
                head_pose.pose.position.z,
            ],
            dtype=np.float32,
        )

        orientation = np.array(
            [
                head_pose.pose.orientation.x,
                head_pose.pose.orientation.y,
                head_pose.pose.orientation.z,
                head_pose.pose.orientation.w,
            ],
            dtype=np.float32,
        )

        output = outputs["head"]
        output[HeadPoseIndex.POSITION] = position
        output[HeadPoseIndex.ORIENTATION] = orientation
        output[HeadPoseIndex.IS_VALID] = head_pose.is_valid
        output[HeadPoseIndex.TIMESTAMP] = int(head_pose.timestamp.device_time)

    def transformed(self, transform_input: OutputSelector) -> RetargeterSubgraph:
        """
        Create a subgraph that applies a 4x4 transform to the head pose output.

        Args:
            transform_input: An OutputSelector providing a TransformMatrix
                (e.g., value_input.output("value")).

        Returns:
            A RetargeterSubgraph with output "head" containing the transformed HeadPose.

        Example:
            head_source = HeadSource("head")
            xform_input = ValueInput("xform", TransformMatrix())
            transformed = head_source.transformed(xform_input.output("value"))
        """
        from ..utilities.head_transform import HeadTransform

        xform_node = HeadTransform(f"{self.name}_transform")
        return xform_node.connect(
            {
                "head": self.output("head"),
                "transform": transform_input,
            }
        )
