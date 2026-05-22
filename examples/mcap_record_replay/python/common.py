# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared pipeline for the record / replay scripts.

Includes hand, controller, and full-body pipeline builders plus the rendering
helpers used by the replay scripts (``HandJoints``, ``HAND_BONES``,
``BODY_BONES``).
"""

import numpy as np

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
    FullBodySource,
    HandsSource,
)
from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    OutputCombiner,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    RetargeterIO,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    NUM_HAND_JOINTS,
    BoolType,
    HandInput,
    HandInputIndex,
)
from isaacteleop.retargeting_engine.tensor_types.indices import BodyJointPicoIndex
from isaacteleop.retargeting_engine.tensor_types.ndarray_types import (
    DLDataType,
    NDArrayType,
)


_ZERO_POSITIONS = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)


HANDS_CHANNEL = "hands"
BODY_JOINT_NAMES = [joint.name for joint in BodyJointPicoIndex]


def _positions_group(name: str) -> TensorGroupType:
    return TensorGroupType(
        name,
        [
            NDArrayType(
                "positions",
                shape=(NUM_HAND_JOINTS, 3),
                dtype=DLDataType.FLOAT,
                dtype_bits=32,
            )
        ],
    )


class HandJoints(BaseRetargeter):
    """Passes hand joint positions + validity through for downstream consumers.

    Zero-fills positions when a hand is not tracked so downstream code can read
    a fixed-shape array every frame.
    """

    def input_spec(self):
        return {
            HandsSource.LEFT: OptionalType(HandInput()),
            HandsSource.RIGHT: OptionalType(HandInput()),
        }

    def output_spec(self):
        return {
            "left_positions": _positions_group("left_positions"),
            "right_positions": _positions_group("right_positions"),
            "left_valid": TensorGroupType("left_valid", [BoolType("v")]),
            "right_valid": TensorGroupType("right_valid", [BoolType("v")]),
        }

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        for side, key in (("left", HandsSource.LEFT), ("right", HandsSource.RIGHT)):
            optional_hand = inputs[key]
            if optional_hand.is_none:
                outputs[f"{side}_valid"][0] = False
                outputs[f"{side}_positions"][0] = _ZERO_POSITIONS.copy()
            else:
                outputs[f"{side}_valid"][0] = True
                outputs[f"{side}_positions"][0] = np.asarray(
                    optional_hand[HandInputIndex.JOINT_POSITIONS],
                    dtype=np.float32,
                )


def build_hand_pipeline():
    hands = HandsSource(name=HANDS_CHANNEL)
    joints = HandJoints(name="hand_joints")
    return joints.connect(
        {
            HandsSource.LEFT: hands.output(HandsSource.LEFT),
            HandsSource.RIGHT: hands.output(HandsSource.RIGHT),
        }
    )


def build_controller_pipeline():
    controllers = ControllersSource(name="controllers")
    return OutputCombiner(
        {
            "controller_left": controllers.output(ControllersSource.LEFT),
            "controller_right": controllers.output(ControllersSource.RIGHT),
        }
    )


def build_full_body_pipeline():
    controllers = ControllersSource(name="controllers")
    full_body = FullBodySource(name="full_body")
    return OutputCombiner(
        {
            "controller_left": controllers.output(ControllersSource.LEFT),
            "controller_right": controllers.output(ControllersSource.RIGHT),
            "full_body": full_body.output(FullBodySource.FULL_BODY),
        }
    )


# PICO body-joint connectivity (parent → child) for skeleton rendering.
# Indices follow BodyJointPicoIndex: 0=PELVIS, 1/2=LEFT/RIGHT_HIP, 3/6/9=SPINE1/2/3,
# 4/5=LEFT/RIGHT_KNEE, 7/8=LEFT/RIGHT_ANKLE, 10/11=LEFT/RIGHT_FOOT, 12=NECK,
# 13/14=LEFT/RIGHT_COLLAR, 15=HEAD, 16/17=LEFT/RIGHT_SHOULDER,
# 18/19=LEFT/RIGHT_ELBOW, 20/21=LEFT/RIGHT_WRIST, 22/23=LEFT/RIGHT_HAND — 24 total.
BODY_BONES: tuple[tuple[int, int], ...] = (
    # Trunk and spine
    (0, 1),
    (0, 2),
    (0, 3),
    (3, 6),
    (6, 9),
    (9, 12),
    (12, 15),
    # Left leg
    (1, 4),
    (4, 7),
    (7, 10),
    # Right leg
    (2, 5),
    (5, 8),
    (8, 11),
    # Left arm
    (12, 13),
    (13, 16),
    (16, 18),
    (18, 20),
    (20, 22),
    # Right arm
    (12, 14),
    (14, 17),
    (17, 19),
    (19, 21),
    (21, 23),
)


# OpenXR hand-joint connectivity (parent → child) for skeleton rendering.
# Indices follow XR_HAND_JOINT_*_EXT: 0=PALM, 1=WRIST, thumb has 4 joints
# (no intermediate), the other 4 fingers have 5 joints each — 26 total.
HAND_BONES: tuple[tuple[int, int], ...] = (
    # Thumb
    (1, 2),
    (2, 3),
    (3, 4),
    (4, 5),
    # Index
    (1, 6),
    (6, 7),
    (7, 8),
    (8, 9),
    (9, 10),
    # Middle
    (1, 11),
    (11, 12),
    (12, 13),
    (13, 14),
    (14, 15),
    # Ring
    (1, 16),
    (16, 17),
    (17, 18),
    (18, 19),
    (19, 20),
    # Little
    (1, 21),
    (21, 22),
    (22, 23),
    (23, 24),
    (24, 25),
)
