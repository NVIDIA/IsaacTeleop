# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared pipeline for the record / replay scripts.

Only ``HandsSource`` is wired in — so ``TeleopSession`` auto-discovers a single
``HandTracker`` and the resulting MCAP contains exactly one channel (``hands``).

The ``HandJoints`` retargeter exposes per-hand joint positions and validity so
that ``replay_hand.py`` can drive a viser scene from the live session step.

To capture more channels (head, controllers), add the corresponding source
nodes here and wire them into a retargeter.
"""

import numpy as np

from isaacteleop.retargeting_engine.deviceio_source_nodes import HandsSource
from isaacteleop.retargeting_engine.interface import BaseRetargeter
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
from isaacteleop.retargeting_engine.tensor_types.ndarray_types import (
    DLDataType,
    NDArrayType,
)


_ZERO_POSITIONS = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)


HANDS_CHANNEL = "hands"


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


def build_pipeline():
    hands = HandsSource(name=HANDS_CHANNEL)
    joints = HandJoints(name="hand_joints")
    return joints.connect(
        {
            HandsSource.LEFT: hands.output(HandsSource.LEFT),
            HandsSource.RIGHT: hands.output(HandsSource.RIGHT),
        }
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
