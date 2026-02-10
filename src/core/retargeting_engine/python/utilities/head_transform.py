# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Head Transform Node - Applies a 4x4 transform to head pose data.

Transforms head position and orientation using a homogeneous transformation
matrix while preserving validity and timestamp fields.

The transform matrix is received as a tensor input from the graph, typically
provided by a TransformSource node.
"""

import numpy as np

from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..tensor_types import HeadPose, TransformMatrix
from .transform_utils import (
    decompose_transform,
    transform_position,
    transform_orientation,
)


# Index of the matrix field within the TransformMatrix TensorGroupType
_MATRIX_INDEX = 0


class HeadTransform(BaseRetargeter):
    """
    Applies a 4x4 homogeneous transform to head pose data.

    Transforms the head position (R @ p + t) and orientation (R_quat * q)
    while passing through is_valid and timestamp unchanged.

    The transform matrix is provided as a tensor input, allowing it to be
    sourced from a TransformSource node in the graph.

    Inputs:
        - "head": HeadPose tensor (position, orientation, is_valid, timestamp)
        - "transform": TransformMatrix tensor containing the (4, 4) matrix

    Outputs:
        - "head": HeadPose tensor with transformed position and orientation

    Example:
        transform_input = PassthroughInput("xform_input", TransformMatrix())
        head_transform = HeadTransform("head_xform")

        transformed = head_transform.connect({
            "head": head_source.output("head"),
            "transform": transform_input.output("value"),
        })
    """

    # Input/output tensor indices for HeadPose
    _POSITION = 0
    _ORIENTATION = 1
    _IS_VALID = 2
    _TIMESTAMP = 3

    def __init__(self, name: str) -> None:
        """
        Initialize head transform node.

        Args:
            name: Unique name for this node.
        """
        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        """Declare head pose and transform matrix inputs."""
        return {
            "head": HeadPose(),
            "transform": TransformMatrix(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare transformed head pose output."""
        return {
            "head": HeadPose()
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Apply the 4x4 transform to head position and orientation.

        Position is transformed as: p' = R @ p + t
        Orientation is transformed as: q' = R_quat * q

        Args:
            inputs: Dict with "head" and "transform" TensorGroups.
            outputs: Dict with "head" TensorGroup to populate.
        """
        # Extract the 4x4 matrix from the transform input
        matrix = np.from_dlpack(inputs["transform"][_MATRIX_INDEX])
        rotation, translation = decompose_transform(matrix)

        inp = inputs["head"]
        out = outputs["head"]

        # Transform position
        position = np.from_dlpack(inp[self._POSITION])
        out[self._POSITION] = transform_position(
            position, rotation, translation
        )

        # Transform orientation
        orientation = np.from_dlpack(inp[self._ORIENTATION])
        out[self._ORIENTATION] = transform_orientation(
            orientation, rotation
        )

        # Pass through unchanged fields
        out[self._IS_VALID] = inp[self._IS_VALID]
        out[self._TIMESTAMP] = inp[self._TIMESTAMP]
