# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Which controller pose a consumer drives from, and that pose as a 7-D ``ee_pose``."""

from __future__ import annotations

import enum

import numpy as np
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import BaseRetargeter, RetargeterIOType
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
    DLDataType,
    NDArrayType,
)
from .rate_limiter import EE_POSE_KEY


class HandPose(enum.Enum):
    """Which standard OpenXR controller pose a consumer drives from.

    Different frames for different jobs, per the OpenXR spec. Grip is the palm centroid,
    for rendering a held object; its -Z runs little finger to thumb, through the fist,
    and is not a pointing direction. Aim's -Z is the pointing ray. A facing read off grip
    therefore turns 1:1 with the hand but has an arbitrary zero.

    The values are the strings ``SO101ClutchRetargeter(controller_pose=...)`` takes, so
    one constant switches the whole app.
    """

    GRIP = "grip"
    AIM = "aim"

    @property
    def indices(self) -> tuple[int, int, int]:
        """``(position, orientation, is_valid)`` in :func:`ControllerInput` for this pose."""
        if self is HandPose.GRIP:
            return (
                ControllerInputIndex.GRIP_POSITION,
                ControllerInputIndex.GRIP_ORIENTATION,
                ControllerInputIndex.GRIP_IS_VALID,
            )
        return (
            ControllerInputIndex.AIM_POSITION,
            ControllerInputIndex.AIM_ORIENTATION,
            ControllerInputIndex.AIM_IS_VALID,
        )


def _pose_type() -> TensorGroupType:
    """The 7-D ``[x, y, z, qx, qy, qz, qw]`` contract the EE-pose nodes share."""
    return TensorGroupType(
        EE_POSE_KEY,
        [NDArrayType("pose", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32)],
    )


class ControllerPoseSource(BaseRetargeter):
    """A controller's pose as an ``ee_pose``, so a rate limiter or gate can take it.

    Emits in whatever reference frame the controller stream is already in; a rigid
    rebase downstream bounds the same metres and radians, so limiting here and
    transforming afterwards is equivalent. Goes **absent** on an invalid pose rather
    than holding the last one -- holding is a governor's job, and a consumer that wants
    to know about tracking loss needs the gap to survive this node.

    Inputs:
        - ``input_device`` -- Optional :func:`ControllerInput`.

    Outputs:
        - ``ee_pose`` -- Optional 7-D ``[x, y, z, qx, qy, qz, qw]`` float32 ``NDArray``.
    """

    def __init__(
        self,
        name: str,
        pose: HandPose = HandPose.GRIP,
        input_device: str = ControllersSource.RIGHT,
    ) -> None:
        """Initialize the controller-pose adapter.

        Args:
            name: Name identifier for this retargeter node.
            pose: Which OpenXR controller pose to read.
            input_device: Controller source key to read the pose from.
        """
        self._input_device = input_device
        self._pose = pose
        super().__init__(name=name)

    @property
    def pose(self) -> HandPose:
        """Which OpenXR controller pose this emits."""
        return self._pose

    def input_spec(self) -> RetargeterIOType:
        """Requires the configured controller (Optional)."""
        return {self._input_device: OptionalType(ControllerInput())}

    def output_spec(self) -> RetargeterIOType:
        """Outputs an Optional absolute 7-D ``ee_pose``."""
        return {EE_POSE_KEY: OptionalType(_pose_type())}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Repacks the pose; goes absent when the controller is untracked."""
        out = outputs[EE_POSE_KEY]
        inp = inputs[self._input_device]
        position_index, orientation_index, valid_index = self._pose.indices
        if inp.is_none or not bool(inp[valid_index]):
            out.set_none()
            return

        position = inp[position_index]
        orientation = inp[orientation_index]
        # Both orientations are already (x, y, z, w), the EE-pose convention.
        out[0] = np.array(
            [
                float(position[0]),
                float(position[1]),
                float(position[2]),
                float(orientation[0]),
                float(orientation[1]),
                float(orientation[2]),
                float(orientation[3]),
            ],
            dtype=np.float32,
        )
