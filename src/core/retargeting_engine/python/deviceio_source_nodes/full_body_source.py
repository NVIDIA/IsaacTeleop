# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Full Body Source Node - DeviceIO to Retargeting Engine converter.

Converts raw FullBodyPosePicoT flatbuffer data to standard FullBodyInput tensor format.
"""

import numpy as np
from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import (
    RetargeterIO,
    RetargeterIOType,
)
from ..interface.tensor_group import TensorGroup
from ..tensor_types import FullBodyInput
from ..tensor_types.standard_types import NUM_BODY_JOINTS_PICO
from .deviceio_tensor_types import DeviceIOFullBodyPosePico

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import FullBodyPosePicoT


class FullBodySource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO FullBodyPosePicoT -> FullBodyInput tensors.

    Inputs:
        - "deviceio_full_body": Raw FullBodyPosePicoT flatbuffer

    Outputs:
        - "full_body": Standard FullBodyInput tensor (positions, orientations, validity)

    Usage:
        body_pose = body_tracker.get_body_pose(session)
        result = full_body_source_node({
            "deviceio_full_body": body_pose
        })
    """

    FULL_BODY = "full_body"

    def __init__(self, name: str) -> None:
        """Initialize stateless full body source node.

        Creates a FullBodyTrackerPico instance for TeleopSession to discover and use.

        Args:
            name: Unique name for this source node
        """
        import isaacteleop.deviceio as deviceio

        self._body_tracker = deviceio.FullBodyTrackerPico()
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        """Get the FullBodyTrackerPico instance.

        Returns:
            The FullBodyTrackerPico instance for TeleopSession to initialize
        """
        return self._body_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll body tracker and return input data.

        Args:
            deviceio_session: The active DeviceIO session.

        Returns:
            Dict with "deviceio_full_body" TensorGroup containing raw
            FullBodyPosePicoT data.
        """
        body_pose = self._body_tracker.get_body_pose(deviceio_session)
        source_inputs = self.input_spec()
        result = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            tg[0] = body_pose
            result[input_name] = tg
        return result

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO full body input."""
        return {
            "deviceio_full_body": DeviceIOFullBodyPosePico(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard full body output."""
        return {
            "full_body": FullBodyInput(),
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Convert DeviceIO FullBodyPosePicoT to standard FullBodyInput tensors.

        Args:
            inputs: Dict with "deviceio_full_body" flatbuffer object
            outputs: Dict with "full_body" TensorGroup
        """
        body_pose: "FullBodyPosePicoT" = inputs["deviceio_full_body"][0]
        group = outputs["full_body"]

        positions = np.zeros((NUM_BODY_JOINTS_PICO, 3), dtype=np.float32)
        orientations = np.zeros((NUM_BODY_JOINTS_PICO, 4), dtype=np.float32)
        valid = np.zeros(NUM_BODY_JOINTS_PICO, dtype=np.uint8)

        if body_pose.joints is not None:
            for i in range(NUM_BODY_JOINTS_PICO):
                joint = body_pose.joints[i]
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

        group[0] = positions
        group[1] = orientations
        group[2] = valid
        group[3] = body_pose.is_active
        timestamp = 0
        if body_pose.timestamp is not None:
            timestamp = body_pose.timestamp.device_time
        group[4] = timestamp
