# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Full Body Source Node - DeviceIO to Retargeting Engine converter.

Converts raw FullBodyPoseT flatbuffer data to standard FullBodyInput tensor format.
"""

import numpy as np
from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import (
    RetargeterIO,
    RetargeterIOType,
)
from ..interface.tensor_group import TensorGroup
from ..tensor_types import FullBodyInput, FullBodyInputIndex
from ..interface.tensor_group_type import OptionalType
from ..tensor_types.standard_types import NUM_BODY_JOINTS
from .deviceio_tensor_types import DeviceIOFullBodyPoseTracked

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import FullBodyPoseT, FullBodyPoseTrackedT


class FullBodySource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO FullBodyPoseT -> FullBodyInput tensors.

    Inputs:
        - "deviceio_full_body": Raw FullBodyPoseT flatbuffer

    Outputs (Optional — absent when body tracking is inactive):
        - "full_body": OptionalTensorGroup (check ``.is_none`` before access)

    Usage:
        body_pose = body_tracker.get_body_pose(session)
        result = full_body_source_node({
            "deviceio_full_body": body_pose
        })
    """

    FULL_BODY = "full_body"

    def __init__(self, name: str) -> None:
        """Initialize stateless full body source node.

        Creates a FullBodyTracker instance for TeleopSession to discover and use.

        Args:
            name: Unique name for this source node
        """
        import isaacteleop.deviceio as deviceio

        self._body_tracker = deviceio.FullBodyTracker()
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        """Get the FullBodyTracker instance.

        Returns:
            The FullBodyTracker instance for TeleopSession to initialize
        """
        return self._body_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll body tracker and return input data.

        Args:
            deviceio_session: The active DeviceIO session.

        Returns:
            Dict with "deviceio_full_body" TensorGroup containing raw
            FullBodyPoseT data.
        """
        body_pose = self._body_tracker.get_body_pose(deviceio_session)
        source_inputs = self.input_spec()
        result: RetargeterIO = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            tg[0] = body_pose
            result[input_name] = tg
        return result

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO full body input."""
        return {
            "deviceio_full_body": DeviceIOFullBodyPoseTracked(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard full body output (Optional — may be absent)."""
        return {
            "full_body": OptionalType(FullBodyInput()),
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """
        Convert DeviceIO FullBodyPoseT to standard FullBodyInput tensors.

        Calls ``set_none()`` on the output when body tracking is inactive.

        Args:
            inputs: Dict with "deviceio_full_body" containing FullBodyPoseTrackedT wrapper
            outputs: Dict with "full_body" OptionalTensorGroup
            context: Shared ComputeContext for the current step (carries GraphTime).
        """
        tracked: "FullBodyPoseTrackedT" = inputs["deviceio_full_body"][0]
        body_pose: "FullBodyPoseT | None" = tracked.data

        if body_pose is None:
            outputs["full_body"].set_none()
            return

        group = outputs["full_body"]

        positions = np.zeros((NUM_BODY_JOINTS, 3), dtype=np.float32)
        orientations = np.zeros((NUM_BODY_JOINTS, 4), dtype=np.float32)
        valid = np.zeros(NUM_BODY_JOINTS, dtype=np.uint8)

        if body_pose.joints is not None:
            for i in range(NUM_BODY_JOINTS):
                joint = body_pose.joints.joints(i)
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
                valid[i] = 1 if joint.is_valid else 0

        group[FullBodyInputIndex.JOINT_POSITIONS] = positions
        group[FullBodyInputIndex.JOINT_ORIENTATIONS] = orientations
        group[FullBodyInputIndex.JOINT_VALID] = valid
