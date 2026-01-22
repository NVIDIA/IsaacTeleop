# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Gripper Retargeter Module.

Retargeter specifically for gripper control based on hand tracking data.
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..interface import BaseRetargeter, RetargeterIO
from ..interface.tensor_group_type import TensorGroupType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HandInput, ControllerInput, FloatType
from ..tensor_types import HandInputIndex, HandJointIndex, ControllerInputIndex


@dataclass
class GripperRetargeterConfig:
    """Configuration for gripper retargeter."""
    hand_side: str = "right"
    gripper_close_meters: float = 0.03
    gripper_open_meters: float = 0.05
    controller_threshold: float = 0.5


class GripperRetargeter(BaseRetargeter):
    """
    Retargeter specifically for gripper control based on hand tracking data.

    This retargeter analyzes the distance between thumb and index finger tips to determine
    whether the gripper should be open or closed. It includes hysteresis to prevent rapid
    toggling between states when the finger distance is near the threshold.
    """

    def __init__(self, config: GripperRetargeterConfig, name: str) -> None:
        self._config = config
        if self._config.hand_side not in ["left", "right"]:
             raise ValueError(f"hand_side must be 'left' or 'right', got: {self._config.hand_side}")

        super().__init__(name=name)

        self._previous_gripper_command = False  # False = open, True = closed

    def input_spec(self) -> RetargeterIO:
        """Requires hand tracking input and controller input."""
        spec = {}

        # Always request hand input
        if self._config.hand_side == "left":
            spec["hand_left"] = HandInput()
        else:
            spec["hand_right"] = HandInput()

        # Always request controller input
        spec[f"controller_{self._config.hand_side}"] = ControllerInput()

        return spec

    def output_spec(self) -> RetargeterIO:
        """Outputs a single float value (-1.0 for closed, 1.0 for open)."""
        return {
            "gripper_command": TensorGroupType("gripper_command", [
                FloatType("command")
            ])
        }

    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """Computes gripper command based on controller trigger (priority) or pinch distance (fallback)."""

        # Try to use controller input first if active
        used_controller = False
        controller_key = f"controller_{self._config.hand_side}"
        if controller_key in inputs:
            controller_group = inputs[controller_key]

            # Check active
            if controller_group[ControllerInputIndex.IS_ACTIVE]:
                used_controller = True
                trigger_value = controller_group[ControllerInputIndex.TRIGGER_VALUE]

                # Use threshold with small hysteresis if needed, but simple threshold for now
                if trigger_value > self._config.controller_threshold:
                    self._previous_gripper_command = True  # Close
                else:
                    self._previous_gripper_command = False  # Open

        # Fallback to hand tracking if controller was not used
        if not used_controller:
            hand_key = f"hand_{self._config.hand_side}"
            hand_group = inputs[hand_key]

            # Check active
            if not hand_group[HandInputIndex.IS_ACTIVE]:
                outputs["gripper_command"][0] = 1.0  # Default open
                return

            # Get joint positions
            # Shape (26, 3)
            joint_positions = np.from_dlpack(hand_group[HandInputIndex.JOINT_POSITIONS])
            joint_valid = np.from_dlpack(hand_group[HandInputIndex.JOINT_VALID])

            # OpenXR indices: Thumb Tip = 5, Index Tip = 10
            # 0: palm, 1: wrist
            # 2: thumb_metacarpal, 3: thumb_proximal, 4: thumb_distal, 5: thumb_tip
            # 6: index_metacarpal, 7: index_proximal, 8: index_intermediate, 9: index_distal, 10: index_tip

            if joint_valid[HandJointIndex.THUMB_TIP] and joint_valid[HandJointIndex.INDEX_TIP]:
                thumb_pos = joint_positions[HandJointIndex.THUMB_TIP]
                index_pos = joint_positions[HandJointIndex.INDEX_TIP]

                distance = np.linalg.norm(thumb_pos - index_pos)

                if distance > self._config.gripper_open_meters:
                    self._previous_gripper_command = False  # Open
                elif distance < self._config.gripper_close_meters:
                    self._previous_gripper_command = True  # Close

        # Output: -1.0 if closed, 1.0 if open (matching IsaacLab implementation)
        outputs["gripper_command"][0] = -1.0 if self._previous_gripper_command else 1.0

