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
from .deviceio_tensor_types import DeviceIOHeadPoseTracked

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import HeadPoseT, HeadPoseTrackedT


class HeadSource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO HeadPoseT → HeadPose tensor.

    Inputs:
        - "deviceio_head": Raw HeadPoseT flatbuffer object from DeviceIO

    Outputs (Optional — absent when head tracking is invalid):
        - "head": OptionalTensorGroup (check ``.is_none`` before access)

    Usage:
        # In TeleopSession, manually poll tracker and pass tracked object
        tracked = head_tracker.get_head(session)
        result = head_source_node({"deviceio_head": tracked})
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
            Dict with "deviceio_head" TensorGroup containing HeadPoseTrackedT.
        """
        tracked = self._head_tracker.get_head(deviceio_session)
        source_inputs = self.input_spec()
        result: RetargeterIO = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            tg[0] = tracked
            result[input_name] = tg
        return result

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO head input."""
        return {"deviceio_head": DeviceIOHeadPoseTracked()}

    def output_spec(self) -> RetargeterIOType:
        """Declare standard head pose output (Optional — may be absent)."""
        return {"head": OptionalType(HeadPose())}

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Convert DeviceIO HeadPoseTrackedT to standard HeadPose tensor.

        Calls ``set_none()`` on the output when head tracking is inactive.

        Args:
            inputs: Dict with "deviceio_head" containing HeadPoseTrackedT wrapper
            outputs: Dict with "head" OptionalTensorGroup
        """
        tracked: "HeadPoseTrackedT" = inputs["deviceio_head"][0]
        head_pose: "HeadPoseT | None" = tracked.data

        output = outputs["head"]
        if head_pose is None:
            output.set_none()
            return

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

        output[HeadPoseIndex.POSITION] = position
        output[HeadPoseIndex.ORIENTATION] = orientation
        output[HeadPoseIndex.IS_VALID] = head_pose.is_valid

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
