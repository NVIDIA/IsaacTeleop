# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Hand Transform Node - Applies a 4x4 transform to hand tracking data.

Transforms all hand joint positions and orientations using a homogeneous
transformation matrix while preserving joint radii, validity, active state,
and timestamp fields.

The transform matrix is received as a tensor input from the graph, typically
provided by a TransformSource node.

Note: All 26 joint positions and orientations are transformed (not just the
wrist) since all joints share the same coordinate frame. Transforming only
the wrist while leaving other joints untransformed would break the hand skeleton.
"""

import copy

import numpy as np

from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HandInput, HandInputIndex, TransformMatrix
from .transform_utils import (
    decompose_transform,
    transform_positions_batch,
    transform_orientations_batch,
)


# Index of the matrix field within the TransformMatrix TensorGroupType
_MATRIX_INDEX = 0


class HandTransform(BaseRetargeter):
    """
    Applies a 4x4 homogeneous transform to hand tracking data.

    Transforms all 26 joint positions (R @ p + t) and orientations (R_quat * q)
    for both left and right hands while passing through joint radii, validity
    flags, active state, and timestamp unchanged.

    The transform matrix is provided as a tensor input, allowing it to be
    sourced from a TransformSource node in the graph.

    Inputs:
        - "hand_left": HandInput tensor (26 joints)
        - "hand_right": HandInput tensor (26 joints)
        - "transform": TransformMatrix tensor containing the (4, 4) matrix

    Outputs:
        - "hand_left": HandInput tensor with transformed joint poses
        - "hand_right": HandInput tensor with transformed joint poses

    Example:
        transform_input = PassthroughInput("xform_input", TransformMatrix())
        hand_transform = HandTransform("hand_xform")

        transformed = hand_transform.connect({
            "hand_left": hand_source.output("hand_left"),
            "hand_right": hand_source.output("hand_right"),
            "transform": transform_input.output("value"),
        })
    """

    LEFT = "hand_left"
    RIGHT = "hand_right"

    def __init__(self, name: str) -> None:
        """
        Initialize hand transform node.

        Args:
            name: Unique name for this node.
        """
        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        """Declare hand and transform matrix inputs."""
        return {
            self.LEFT: HandInput(),
            self.RIGHT: HandInput(),
            "transform": TransformMatrix(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare transformed hand output specs for left and right."""
        return {
            self.LEFT: HandInput(),
            self.RIGHT: HandInput(),
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Apply the 4x4 transform to all hand joint positions and orientations.

        Position is transformed as: p' = R @ p + t (batch over 26 joints)
        Orientation is transformed as: q' = R_quat * q (batch over 26 joints)
        All other fields (radii, validity, active, timestamp) are copied unchanged.

        Args:
            inputs: Dict with "hand_left", "hand_right", and "transform" TensorGroups.
            outputs: Dict with "hand_left" and "hand_right" TensorGroups.
        """
        matrix = np.from_dlpack(inputs["transform"][_MATRIX_INDEX])
        rotation, translation = decompose_transform(matrix)

        self._transform_hand(inputs[self.LEFT], outputs[self.LEFT], rotation, translation)
        self._transform_hand(inputs[self.RIGHT], outputs[self.RIGHT], rotation, translation)

    @staticmethod
    def _transform_hand(
        inp: TensorGroup,
        out: TensorGroup,
        rotation: np.ndarray,
        translation: np.ndarray,
    ) -> None:
        """Apply the transform to a single hand's joint data."""
        # Deep-copy all fields from input to output (avoid aliasing)
        for i in range(len(inp)):
            out[i] = copy.deepcopy(inp[i])

        # Transform pose fields in-place on the output buffers
        transform_positions_batch(np.from_dlpack(out[HandInputIndex.JOINT_POSITIONS]), rotation, translation)
        transform_orientations_batch(np.from_dlpack(out[HandInputIndex.JOINT_ORIENTATIONS]), rotation)
