# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Controller Transform Node - Applies a 4x4 transform to controller pose data.

Transforms controller grip and aim positions/orientations using a homogeneous
transformation matrix while preserving button/axis input fields.

The transform matrix is received as a tensor input from the graph, typically
provided by a TransformSource node.
"""

import copy

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
        transform_input = ValueInput("xform_input", TransformMatrix())
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
        All other fields (buttons, axes, is_active) are copied unchanged.

        Args:
            inputs: Dict with "controller_left", "controller_right", and "transform" TensorGroups.
            outputs: Dict with "controller_left" and "controller_right" TensorGroups.
        """
        matrix = np.from_dlpack(inputs["transform"][_MATRIX_INDEX])
        rotation, translation = decompose_transform(matrix)

        self._transform_controller(
            inputs[self.LEFT], outputs[self.LEFT], rotation, translation
        )
        self._transform_controller(
            inputs[self.RIGHT], outputs[self.RIGHT], rotation, translation
        )

    @staticmethod
    def _transform_controller(
        inp: TensorGroup,
        out: TensorGroup,
        rotation: np.ndarray,
        translation: np.ndarray,
    ) -> None:
        """Apply the transform to a single controller's data."""
        # Deep-copy all fields from input to output (avoid aliasing)
        for i in range(len(inp)):
            out[i] = copy.deepcopy(inp[i])

        # Transform pose fields in-place on the output buffers
        transform_position(
            np.from_dlpack(out[ControllerInputIndex.GRIP_POSITION]),
            rotation,
            translation,
        )
        transform_orientation(
            np.from_dlpack(out[ControllerInputIndex.GRIP_ORIENTATION]), rotation
        )
        transform_position(
            np.from_dlpack(out[ControllerInputIndex.AIM_POSITION]),
            rotation,
            translation,
        )
        transform_orientation(
            np.from_dlpack(out[ControllerInputIndex.AIM_ORIENTATION]), rotation
        )
