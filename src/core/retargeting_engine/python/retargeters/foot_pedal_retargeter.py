# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Foot Pedal Retargeter Module.

Provides root command retargeting from generic 3-axis foot pedal input
(forward/backward pedals + rudder), mirroring Isaac OS LowerBodyController logic.
"""

import numpy as np
from dataclasses import dataclass

from ..interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from ..interface.retargeter_core_types import RetargeterIO
from ..interface.tensor_group_type import TensorGroupType, OptionalType
from ..tensor_types import (
    Generic3AxisPedalInput,
    NDArrayType,
    DLDataType,
    Generic3AxisPedalInputIndex,
)

DEFAULT_MAX_LINEAR_VEL_MPS = 1.0
DEFAULT_MAX_ANGULAR_VEL_RADPS = 1.0
DEFAULT_MIN_SQUAT_POS = 0.4
DEFAULT_MAX_SQUAT_POS = 0.72
DEFAULT_DEADZONE_THRESHOLD = 0.05
DEFAULT_YAW_RUDDER_THRESHOLD = 0.1
DEFAULT_STRAFE_RUDDER_THRESHOLD = 0.2
DEFAULT_STRAFE_PEDAL_PRESSED_THRESHOLD = 0.1


@dataclass
class FootPedalRootCmdRetargeterConfig:
    """Configuration for foot pedal root command retargeter.

    Mirrors Isaac OS LowerBodyController parameters. No gamepad mode.
    """

    max_linear_vel_mps: float = DEFAULT_MAX_LINEAR_VEL_MPS
    max_angular_vel_radps: float = DEFAULT_MAX_ANGULAR_VEL_RADPS
    min_squat_pos: float = DEFAULT_MIN_SQUAT_POS
    max_squat_pos: float = DEFAULT_MAX_SQUAT_POS
    deadzone_threshold: float = DEFAULT_DEADZONE_THRESHOLD
    yaw_rudder_threshold: float = DEFAULT_YAW_RUDDER_THRESHOLD
    strafe_rudder_threshold: float = DEFAULT_STRAFE_RUDDER_THRESHOLD
    strafe_pedal_pressed_threshold: float = DEFAULT_STRAFE_PEDAL_PRESSED_THRESHOLD
    mode: str = "horizontal"  # "horizontal" | "vertical"


class FootPedalRootCmdRetargeter(BaseRetargeter):
    """
    Maps 3-axis foot pedal input to root command [vel_x, vel_y, rot_vel_z, hip_height].

    There are two rudder pedal motion modes:

    Horizontal mode:
    - Right pedal: forward motion
    - Left pedal: backward motion
    - Rudder rotation (no pedal pressed): robot rotation
    - Rudder rotation (pedal pressed): sidestepping in direction of rotation
    Vertical mode:
    - Left pedal: drives hip height between min_squat_pos and max_squat_pos
    - Right pedal: not used in vertical mode
    - Rudder: yaw rotation when no pedal pressed
    """

    def __init__(self, config: FootPedalRootCmdRetargeterConfig, name: str) -> None:
        super().__init__(name=name)
        self._config = config

    def _apply_deadzone(self, value: float) -> float:
        """Symmetric deadzone: values in [-threshold, +threshold] become 0."""
        if abs(value) <= self._config.deadzone_threshold:
            return 0.0
        return value

    def input_spec(self) -> RetargeterIOType:
        """Requires one pedal input (Optional)."""
        return {
            "pedals": OptionalType(Generic3AxisPedalInput()),
        }

    def output_spec(self) -> RetargeterIOType:
        """Outputs a 4D root command vector [vel_x, vel_y, rot_vel_z, hip_height]."""
        return {
            "root_command": TensorGroupType(
                "root_command",
                [
                    NDArrayType(
                        "command", shape=(4,), dtype=DLDataType.FLOAT, dtype_bits=32
                    )
                ],
            )
        }

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """Computes root command from pedal input."""
        root_cmd = outputs["root_command"]

        vel_x = 0.0
        vel_y = 0.0
        rot_vel_z = 0.0
        hip_height = self._config.max_squat_pos

        pedal_group = inputs["pedals"]
        if pedal_group.is_none:
            cmd = np.array([vel_x, vel_y, rot_vel_z, hip_height], dtype=np.float32)
            root_cmd[0] = cmd
            return

        left_pedal = self._apply_deadzone(
            float(pedal_group[Generic3AxisPedalInputIndex.LEFT_PEDAL])
        )
        right_pedal = self._apply_deadzone(
            float(pedal_group[Generic3AxisPedalInputIndex.RIGHT_PEDAL])
        )
        rudder = float(
            pedal_group[Generic3AxisPedalInputIndex.RUDDER]
        )  # No deadzone per OS.
        max_pedal = max(left_pedal, right_pedal)

        cfg = self._config
        max_lin = cfg.max_linear_vel_mps
        max_ang = cfg.max_angular_vel_radps

        if cfg.mode == "vertical":
            # Vertical mode: left pedal drives hip height; linear vel zeroed.
            if left_pedal > 0:
                hip_height = cfg.max_squat_pos - left_pedal * (
                    cfg.max_squat_pos - cfg.min_squat_pos
                )
                hip_height = max(cfg.min_squat_pos, min(cfg.max_squat_pos, hip_height))
            # Rudder still processed below for yaw when no pedal pressed.
        else:
            # Horizontal mode: forward = right - left.
            forward_cmd = right_pedal - left_pedal
            vel_x = np.clip(forward_cmd * max_lin, -max_lin, max_lin).item()

        # Rudder: strafe when pedal pressed and |rudder| > threshold; else yaw when no pedal.
        pedal_pressed = max_pedal > cfg.strafe_pedal_pressed_threshold
        if pedal_pressed:
            strafe_active = abs(rudder) > cfg.strafe_rudder_threshold
            if strafe_active:
                vel_x = 0.0
                vel_y = np.clip(rudder * max_lin * max_pedal, -max_lin, max_lin).item()
        else:
            if abs(rudder) > cfg.yaw_rudder_threshold:
                rot_vel_z = np.clip(rudder * max_ang, -max_ang, max_ang).item()

        cmd = np.array([vel_x, vel_y, rot_vel_z, hip_height], dtype=np.float32)
        root_cmd[0] = cmd
