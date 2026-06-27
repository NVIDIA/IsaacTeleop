# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Adapted by X. Tian JP Tech. Initiatives Inc. for Foottroller Integration
"""
Foottroller Retargeter Module.

Provides root command retargeting from foottroller input
(stick_x, stick_y, LF_heading, LF_tilt, RF_heading, RF_tilt, TS_A, TS_B, TS_C, TS_D).
"""

import numpy as np
from dataclasses import dataclass

from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    RetargeterIO,
    ComputeContext,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    TensorGroupType,
    OptionalType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    FoottrollerInput,
    NDArrayType,
    DLDataType,
    FoottrollerInputIndex,
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
class FoottrollerRootCmdRetargeterConfig:
    """Configuration for foot pedal root command retargeter."""

    max_linear_vel_mps: float = DEFAULT_MAX_LINEAR_VEL_MPS
    max_angular_vel_radps: float = DEFAULT_MAX_ANGULAR_VEL_RADPS
    min_squat_pos: float = DEFAULT_MIN_SQUAT_POS
    max_squat_pos: float = DEFAULT_MAX_SQUAT_POS
    deadzone_threshold: float = DEFAULT_DEADZONE_THRESHOLD
    yaw_rudder_threshold: float = DEFAULT_YAW_RUDDER_THRESHOLD
    strafe_rudder_threshold: float = DEFAULT_STRAFE_RUDDER_THRESHOLD
    strafe_pedal_pressed_threshold: float = DEFAULT_STRAFE_PEDAL_PRESSED_THRESHOLD
    mode: str = "horizontal"  # "horizontal" | "vertical"


class FoottrollerRootCmdRetargeter(BaseRetargeter):
    """
    Maps foottroller input to root command [vel_x, vel_y, rot_vel_z, hip_height].

    There are two rudder pedal motion modes:

    stick_y : move forward or backward
    stick_x : move left or right
    rot_vel_z: evaluated based on rotation of right foot after pressing the ground when TS_D is true, TS_C is false, and TS_A or TS_B is true
    hip_height: hip_height rate determined by rotation of right foot after pressing the ground when TS_C is true, TS_D is false, and TS_A or TS_B is true
    """

    def __init__(self, config: FoottrollerRootCmdRetargeterConfig, name: str) -> None:
        super().__init__(name=name)
        self._config = config
        self.pre_TS_A = False
        self.pre_TS_B = False
        self.pre_TS_C = False
        self.pre_TS_D = False
        self.heading_RF_ref = 0.0
        self.heading_LF_ref = 0.0
        self.cur_hip_height = self._config.max_squat_pos

    def _apply_deadzone(self, value: float) -> float:
        """Symmetric deadzone: values in [-threshold, +threshold] become 0."""
        if abs(value) <= self._config.deadzone_threshold:
            return 0.0
        return value

    def input_spec(self) -> RetargeterIOType:
        """Requires one pedal input (Optional)."""
        return {
            # "foottroller" is the input group name for filtering purpose comment by XT
            "foottroller": OptionalType(FoottrollerInput()),
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

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        """Computes root command from foottroller input."""
        root_cmd = outputs["root_command"]

        vel_x = 0.0
        vel_y = 0.0
        rot_vel_z = 0.0
        hip_height = self._config.max_squat_pos

        foottroller_group = inputs["foottroller"]
        if foottroller_group.is_none:
            cmd = np.array([vel_x, vel_y, rot_vel_z, hip_height], dtype=np.float32)
            root_cmd[0] = cmd
            return

        stick_x = self._apply_deadzone(
            float(foottroller_group[FoottrollerInputIndex.STICK_X])
        )
        stick_y = self._apply_deadzone(
            float(foottroller_group[FoottrollerInputIndex.STICK_Y])
        )
        RF_heading = float(
            foottroller_group[FoottrollerInputIndex.LF_HEADING]
        )  # No deadzone per OS.
        RF_heading = RF_heading * 180.0
        LF_tilt = float(foottroller_group[FoottrollerInputIndex.LF_TILT])
        LF_tilt = LF_tilt * 128.0
        LF_heading = float(foottroller_group[FoottrollerInputIndex.RF_HEADING])
        LF_heading = LF_heading * 180.0
        RF_tilt = float(foottroller_group[FoottrollerInputIndex.RF_TILT])
        RF_tilt = RF_tilt * 128.0
        TS_A = foottroller_group[FoottrollerInputIndex.TS_A]
        TS_B = foottroller_group[FoottrollerInputIndex.TS_B]
        TS_C = foottroller_group[FoottrollerInputIndex.TS_C]
        TS_D = foottroller_group[FoottrollerInputIndex.TS_D]

        temp_btn_val = 0.0
        if TS_A:  # LF heel
            temp_btn_val = temp_btn_val + 1.0
        if TS_B:  # LF front
            temp_btn_val = temp_btn_val + 2.0
        if TS_C:  # RF heel
            temp_btn_val = temp_btn_val + 4.0
        if TS_D:  # RF front
            temp_btn_val = temp_btn_val + 8.0

        rot_vel_z = 0.0
        if TS_A or TS_B:  # require left foot to press the ground
            if not self.pre_TS_C and TS_C and not TS_D:
                self.heading_RF_ref = RF_heading
            if TS_C and not TS_D:
                delta_h_rf = RF_heading - self.heading_RF_ref
                if delta_h_rf > 180.0:
                    delta_h_rf = delta_h_rf - 360.0
                elif delta_h_rf < -180:
                    delta_h_rf = delta_h_rf + 360.0
                if delta_h_rf > 5.0:
                    rot_vel_z = delta_h_rf - 4.0
                elif delta_h_rf < -5.0:
                    rot_vel_z = delta_h_rf + 4.0

            if not self.pre_TS_D and TS_D and not TS_C:
                self.heading_RF_ref = RF_heading
            if TS_D and not TS_C:
                delta_h_rf = RF_heading - self.heading_RF_ref
                if delta_h_rf > 180.0:
                    delta_h_rf = delta_h_rf - 360.0
                elif delta_h_rf < -180:
                    delta_h_rf = delta_h_rf + 360.0
                if delta_h_rf > 5.0:
                    rot_vel_z = delta_h_rf - 4.0
                elif delta_h_rf < -5.0:
                    rot_vel_z = delta_h_rf + 4.0

        hip_height_rate = 0.0
        if TS_C or TS_D:
            if not self.pre_TS_A and TS_A and not TS_B:
                self.heading_LF_ref = LF_heading
            if TS_A and not TS_B:
                delta_h_lf = LF_heading - self.heading_LF_ref
                if delta_h_lf > 180.0:
                    delta_h_lf = delta_h_lf - 360.0
                elif delta_h_lf < -180:
                    delta_h_lf = delta_h_lf + 360.0
                if delta_h_lf > 5.0:
                    hip_height_rate = delta_h_lf - 4.0
                elif delta_h_lf < -5.0:
                    hip_height_rate = delta_h_lf + 4.0

        self.cur_hip_height = self.cur_hip_height + hip_height_rate * 0.0001
        if self.cur_hip_height > self._config.max_squat_pos:
            self.cur_hip_height = self._config.max_squat_pos
        elif self.cur_hip_height < self._config.min_squat_pos:
            self.cur_hip_height = self._config.min_squat_pos

        hip_height = self.cur_hip_height

        self.pre_TS_A = TS_A
        self.pre_TS_B = TS_B
        self.pre_TS_C = TS_C
        self.pre_TS_D = TS_D

        cfg = self._config
        max_lin = cfg.max_linear_vel_mps
        # max_ang = cfg.max_angular_vel_radps

        vel_x = np.clip(stick_x * max_lin, -max_lin, max_lin).item()
        vel_y = -np.clip(stick_y * max_lin, -max_lin, max_lin).item()
        # rot_vel_z = temp_btn_val     # for debugging used to check button press states
        # hip_height = RF_heading          # for debugging
        cmd = np.array([vel_x, vel_y, rot_vel_z, hip_height], dtype=np.float32)
        root_cmd[0] = cmd
