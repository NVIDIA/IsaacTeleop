# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
TriHand Hybrid Retargeter Module.

Maps either VR controller inputs (trigger/squeeze heuristic) or hand tracking
data (geometric finger flex angles) to G1 robot TriHand joint angles.
Controller input takes priority when both are present.
"""

import numpy as np
from typing import List
from dataclasses import dataclass

from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tensor_group import (
    TensorGroup,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import OptionalType
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
    HandInput,
    HandInputIndex,
    HandJointIndex,
    RobotHandJoints,
)


def _flex_angle(parent: np.ndarray, child: np.ndarray, grandchild: np.ndarray) -> float:
    """Compute the flex angle between three joint positions.

    The angle is measured between vectors (parent->child) and (child->grandchild).
    Returns 0 for a straight finger, positive for flexion.
    """
    v1 = child - parent
    v2 = grandchild - child
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-8 or n2 < 1e-8:
        return 0.0
    cos_angle = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    # A straight finger has cos ~1.0 (angle ~0); curled finger has cos < 1.
    # Return the deviation from straight as a positive flex value.
    return float(np.arccos(cos_angle))


@dataclass
class TriHandHybridConfig:
    """Configuration for the hybrid TriHand retargeter.

    Attributes:
        hand_joint_names: List of joint names in the robot hand (in order).
        side: Which side to use ("left" or "right").
    """

    hand_joint_names: List[str]
    side: str = "left"


class TriHandHybridRetargeter(BaseRetargeter):
    """Maps controller OR hand tracking to 7-DOF TriHand joint angles.

    When controller input is present, uses the same trigger/squeeze heuristic
    as :class:`TriHandMotionControllerRetargeter`.  When only hand tracking is
    available, computes geometric flex angles from the OpenXR joint skeleton.

    Output DOF order (same as TriHandMotionControllerRetargeter):
        0. Thumb Rotation
        1. Thumb Middle/Proximal
        2. Thumb Distal
        3. Index Proximal
        4. Index Distal
        5. Middle Proximal
        6. Middle Distal
    """

    THUMB_PROXIMAL_SCALE = 0.4
    THUMB_DISTAL_SCALE = 0.7
    THUMB_ROTATION_TRIGGER_SCALE = 0.5
    THUMB_ROTATION_SQUEEZE_SCALE = 0.5

    def __init__(self, config: TriHandHybridConfig, name: str) -> None:
        self._config = config
        self._hand_joint_names = config.hand_joint_names
        self._side = config.side.lower()

        if self._side not in ["left", "right"]:
            raise ValueError(f"side must be 'left' or 'right', got: {self._side}")

        self._is_left = self._side == "left"

        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {
            f"controller_{self._side}": OptionalType(ControllerInput()),
            f"hand_{self._side}": OptionalType(HandInput()),
        }

    def output_spec(self) -> RetargeterIOType:
        return {
            "hand_joints": RobotHandJoints(
                f"hand_joints_{self._side}", self._hand_joint_names
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        output_group = outputs["hand_joints"]

        controller_group = inputs[f"controller_{self._side}"]
        hand_group = inputs[f"hand_{self._side}"]

        if not controller_group.is_none:
            hand_joints = self._map_from_controller(controller_group)
        elif not hand_group.is_none:
            hand_joints = self._map_from_hand_tracking(hand_group)
        else:
            for i in range(len(self._hand_joint_names)):
                output_group[i] = 0.0
            return

        if self._is_left:
            hand_joints = -hand_joints

        for i in range(min(len(self._hand_joint_names), 7)):
            output_group[i] = float(hand_joints[i])

    # -- Controller path (same heuristic as TriHandMotionControllerRetargeter) --

    def _map_from_controller(self, controller_group) -> np.ndarray:
        trigger = float(controller_group[ControllerInputIndex.TRIGGER_VALUE])
        squeeze = float(controller_group[ControllerInputIndex.SQUEEZE_VALUE])

        joints = np.zeros(7, dtype=np.float32)

        thumb_button = max(trigger, squeeze)
        thumb_angle = -thumb_button
        thumb_rotation = (
            self.THUMB_ROTATION_TRIGGER_SCALE * trigger
            - self.THUMB_ROTATION_SQUEEZE_SCALE * squeeze
        )
        if not self._is_left:
            thumb_rotation = -thumb_rotation

        joints[0] = thumb_rotation
        joints[1] = thumb_angle * self.THUMB_PROXIMAL_SCALE
        joints[2] = thumb_angle * self.THUMB_DISTAL_SCALE
        joints[3] = trigger
        joints[4] = trigger
        joints[5] = squeeze
        joints[6] = squeeze

        return joints

    # -- Hand tracking path (geometric flex angles) --

    def _map_from_hand_tracking(self, hand_group) -> np.ndarray:
        positions = np.from_dlpack(hand_group[HandInputIndex.JOINT_POSITIONS])
        valid = np.from_dlpack(hand_group[HandInputIndex.JOINT_VALID])

        joints = np.zeros(7, dtype=np.float32)

        # Thumb rotation: angle between thumb metacarpal direction and
        # a reference direction in the palm plane.
        if (
            valid[HandJointIndex.WRIST]
            and valid[HandJointIndex.THUMB_METACARPAL]
            and valid[HandJointIndex.THUMB_PROXIMAL]
            and valid[HandJointIndex.INDEX_PROXIMAL]
        ):
            wrist = positions[HandJointIndex.WRIST]
            thumb_mc = positions[HandJointIndex.THUMB_METACARPAL]
            thumb_prox = positions[HandJointIndex.THUMB_PROXIMAL]
            index_prox = positions[HandJointIndex.INDEX_PROXIMAL]

            # Palm reference direction: wrist -> index proximal
            palm_dir = index_prox - wrist
            palm_norm = np.linalg.norm(palm_dir)
            # Thumb direction: metacarpal -> proximal
            thumb_dir = thumb_prox - thumb_mc
            thumb_norm = np.linalg.norm(thumb_dir)

            if palm_norm > 1e-8 and thumb_norm > 1e-8:
                palm_dir = palm_dir / palm_norm
                thumb_dir = thumb_dir / thumb_norm
                cos_a = np.clip(np.dot(palm_dir, thumb_dir), -1.0, 1.0)
                joints[0] = float(np.arccos(cos_a))
                if not self._is_left:
                    joints[0] = -joints[0]

        # Thumb proximal/distal flex
        if (
            valid[HandJointIndex.THUMB_METACARPAL]
            and valid[HandJointIndex.THUMB_PROXIMAL]
            and valid[HandJointIndex.THUMB_DISTAL]
            and valid[HandJointIndex.THUMB_TIP]
        ):
            joints[1] = _flex_angle(
                positions[HandJointIndex.THUMB_METACARPAL],
                positions[HandJointIndex.THUMB_PROXIMAL],
                positions[HandJointIndex.THUMB_DISTAL],
            )
            joints[2] = _flex_angle(
                positions[HandJointIndex.THUMB_PROXIMAL],
                positions[HandJointIndex.THUMB_DISTAL],
                positions[HandJointIndex.THUMB_TIP],
            )

        # Index proximal/distal flex
        if (
            valid[HandJointIndex.INDEX_PROXIMAL]
            and valid[HandJointIndex.INDEX_INTERMEDIATE]
            and valid[HandJointIndex.INDEX_DISTAL]
            and valid[HandJointIndex.INDEX_TIP]
        ):
            joints[3] = _flex_angle(
                positions[HandJointIndex.INDEX_PROXIMAL],
                positions[HandJointIndex.INDEX_INTERMEDIATE],
                positions[HandJointIndex.INDEX_DISTAL],
            )
            joints[4] = _flex_angle(
                positions[HandJointIndex.INDEX_INTERMEDIATE],
                positions[HandJointIndex.INDEX_DISTAL],
                positions[HandJointIndex.INDEX_TIP],
            )

        # Middle proximal/distal flex
        if (
            valid[HandJointIndex.MIDDLE_PROXIMAL]
            and valid[HandJointIndex.MIDDLE_INTERMEDIATE]
            and valid[HandJointIndex.MIDDLE_DISTAL]
            and valid[HandJointIndex.MIDDLE_TIP]
        ):
            joints[5] = _flex_angle(
                positions[HandJointIndex.MIDDLE_PROXIMAL],
                positions[HandJointIndex.MIDDLE_INTERMEDIATE],
                positions[HandJointIndex.MIDDLE_DISTAL],
            )
            joints[6] = _flex_angle(
                positions[HandJointIndex.MIDDLE_INTERMEDIATE],
                positions[HandJointIndex.MIDDLE_DISTAL],
                positions[HandJointIndex.MIDDLE_TIP],
            )

        return joints


class TriHandBiManualHybridRetargeter(BaseRetargeter):
    """Bimanual wrapper around two :class:`TriHandHybridRetargeter` instances.

    Each side independently selects controller or hand tracking based on
    availability, then results are combined into a single joint vector.
    """

    def __init__(
        self,
        left_config: TriHandHybridConfig,
        right_config: TriHandHybridConfig,
        target_joint_names: List[str],
        name: str,
    ) -> None:
        self._target_joint_names = target_joint_names

        super().__init__(name=name)

        left_config.side = "left"
        right_config.side = "right"

        self._left = TriHandHybridRetargeter(left_config, name=f"{name}_left")
        self._right = TriHandHybridRetargeter(right_config, name=f"{name}_right")

        left_joints = left_config.hand_joint_names
        right_joints = right_config.hand_joint_names

        self._left_indices = []
        self._right_indices = []
        self._output_indices_left = []
        self._output_indices_right = []

        for i, jname in enumerate(target_joint_names):
            if jname in left_joints:
                self._output_indices_left.append(i)
                self._left_indices.append(left_joints.index(jname))
            elif jname in right_joints:
                self._output_indices_right.append(i)
                self._right_indices.append(right_joints.index(jname))

    def input_spec(self) -> RetargeterIOType:
        return {
            "controller_left": OptionalType(ControllerInput()),
            "controller_right": OptionalType(ControllerInput()),
            "hand_left": OptionalType(HandInput()),
            "hand_right": OptionalType(HandInput()),
        }

    def output_spec(self) -> RetargeterIOType:
        return {
            "hand_joints": RobotHandJoints(
                "hand_joints_bimanual", self._target_joint_names
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        left_outputs: RetargeterIO = {
            "hand_joints": TensorGroup(self._left.output_spec()["hand_joints"])
        }
        right_outputs: RetargeterIO = {
            "hand_joints": TensorGroup(self._right.output_spec()["hand_joints"])
        }

        left_inputs = {
            "controller_left": inputs["controller_left"],
            "hand_left": inputs["hand_left"],
        }
        right_inputs = {
            "controller_right": inputs["controller_right"],
            "hand_right": inputs["hand_right"],
        }

        self._left.compute(left_inputs, left_outputs, context=context)
        self._right.compute(right_inputs, right_outputs, context=context)

        combined = outputs["hand_joints"]
        for src, dst in zip(self._left_indices, self._output_indices_left):
            combined[dst] = float(left_outputs["hand_joints"][src])
        for src, dst in zip(self._right_indices, self._output_indices_right):
            combined[dst] = float(right_outputs["hand_joints"][src])
