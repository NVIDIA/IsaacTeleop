# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Controller Transform Node - Applies a 4x4 transform to controller pose data.

Transforms controller grip and aim positions/orientations using a homogeneous
transformation matrix while preserving button/axis input fields.

The transform matrix is received as a tensor input from the graph, typically
provided by a TransformSource node.
"""

import numpy as np

from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import ControllerInput, ControllerInputIndex, TransformMatrix
from .transform_utils import (
    decompose_transform,
    transform_position,
    transform_orientation,
)


# Index of the matrix field within the TransformMatrix TensorGroupType
_MATRIX_INDEX = 0


class ControllerTransform(BaseRetargeter):
    """
    Applies a 4x4 homogeneous transform to controller pose data.

    Transforms grip and aim positions (R @ p + t) and orientations (R_quat * q)
    for both left and right controllers while passing through all button/axis
    inputs unchanged.

    The transform matrix is provided as a tensor input, allowing it to be
    sourced from a TransformSource node in the graph.

    Inputs:
        - "controller_left": ControllerInput tensor
        - "controller_right": ControllerInput tensor
        - "transform": TransformMatrix tensor containing the (4, 4) matrix

    Outputs:
        - "controller_left": ControllerInput tensor with transformed poses
        - "controller_right": ControllerInput tensor with transformed poses

    Example:
        transform_input = PassthroughInput("xform_input", TransformMatrix())
        controller_transform = ControllerTransform("ctrl_xform")

        transformed = controller_transform.connect({
            "controller_left": ctrl_source.output("controller_left"),
            "controller_right": ctrl_source.output("controller_right"),
            "transform": transform_input.output("value"),
        })
    """

    LEFT = "controller_left"
    RIGHT = "controller_right"

    def __init__(self, name: str) -> None:
        """
        Initialize controller transform node.

        Args:
            name: Unique name for this node.
        """
        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        """Declare controller and transform matrix inputs."""
        return {
            self.LEFT: ControllerInput(),
            self.RIGHT: ControllerInput(),
            "transform": TransformMatrix(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare transformed controller output specs for left and right."""
        return {
            self.LEFT: ControllerInput(),
            self.RIGHT: ControllerInput(),
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Apply the 4x4 transform to controller grip and aim poses.

        Position is transformed as: p' = R @ p + t
        Orientation is transformed as: q' = R_quat * q
        Button/axis inputs are passed through unchanged.

        Args:
            inputs: Dict with "controller_left", "controller_right", and "transform" TensorGroups.
            outputs: Dict with "controller_left" and "controller_right" TensorGroups.
        """
        # Extract the 4x4 matrix from the transform input
        matrix = np.from_dlpack(inputs["transform"][_MATRIX_INDEX])
        rotation, translation = decompose_transform(matrix)

        self._transform_controller(inputs[self.LEFT], outputs[self.LEFT], rotation, translation)
        self._transform_controller(inputs[self.RIGHT], outputs[self.RIGHT], rotation, translation)

    def _transform_controller(
        self,
        inp: TensorGroup,
        out: TensorGroup,
        rotation: np.ndarray,
        translation: np.ndarray,
    ) -> None:
        """Apply the transform to a single controller's data."""
        # Transform grip pose
        grip_pos = np.from_dlpack(inp[ControllerInputIndex.GRIP_POSITION])
        grip_ori = np.from_dlpack(inp[ControllerInputIndex.GRIP_ORIENTATION])
        out[ControllerInputIndex.GRIP_POSITION] = transform_position(
            grip_pos, rotation, translation
        )
        out[ControllerInputIndex.GRIP_ORIENTATION] = transform_orientation(
            grip_ori, rotation
        )

        # Transform aim pose
        aim_pos = np.from_dlpack(inp[ControllerInputIndex.AIM_POSITION])
        aim_ori = np.from_dlpack(inp[ControllerInputIndex.AIM_ORIENTATION])
        out[ControllerInputIndex.AIM_POSITION] = transform_position(
            aim_pos, rotation, translation
        )
        out[ControllerInputIndex.AIM_ORIENTATION] = transform_orientation(
            aim_ori, rotation
        )

        # Pass through all button/axis inputs unchanged
        out[ControllerInputIndex.PRIMARY_CLICK] = inp[ControllerInputIndex.PRIMARY_CLICK]
        out[ControllerInputIndex.SECONDARY_CLICK] = inp[ControllerInputIndex.SECONDARY_CLICK]
        out[ControllerInputIndex.THUMBSTICK_CLICK] = inp[ControllerInputIndex.THUMBSTICK_CLICK]
        out[ControllerInputIndex.THUMBSTICK_X] = inp[ControllerInputIndex.THUMBSTICK_X]
        out[ControllerInputIndex.THUMBSTICK_Y] = inp[ControllerInputIndex.THUMBSTICK_Y]
        out[ControllerInputIndex.SQUEEZE_VALUE] = inp[ControllerInputIndex.SQUEEZE_VALUE]
        out[ControllerInputIndex.TRIGGER_VALUE] = inp[ControllerInputIndex.TRIGGER_VALUE]
        out[ControllerInputIndex.IS_ACTIVE] = inp[ControllerInputIndex.IS_ACTIVE]
