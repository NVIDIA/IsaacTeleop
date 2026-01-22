# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Locomotion Retargeter Module.

Provides retargeters for generating locomotion commands from VR controller inputs.
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..interface import BaseRetargeter, RetargeterIO
from ..interface.tensor_group_type import TensorGroupType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import ControllerInput, NDArrayType, DLDataType
from ..tensor_types import ControllerInputIndex


@dataclass
class LocomotionFixedRootCmdRetargeterConfig:
    """Configuration for fixed root command retargeter."""
    hip_height: float = 0.72


class LocomotionFixedRootCmdRetargeter(BaseRetargeter):
    """
    Provides fixed root commands (velocity zero, fixed hip height).

    Useful for standing still or when motion controllers are not available but the pipeline expects
    locomotion commands.
    """

    def __init__(self, config: LocomotionFixedRootCmdRetargeterConfig, name: str) -> None:
        super().__init__(name=name)
        self._config = config

    def input_spec(self) -> RetargeterIO:
        """No inputs required."""
        return {}

    def output_spec(self) -> RetargeterIO:
        """Outputs a 4D root command vector [vel_x, vel_y, rot_vel_z, hip_height]."""
        return {
            "root_command": TensorGroupType("root_command", [
                NDArrayType("command", shape=(4,), dtype=DLDataType.FLOAT, dtype_bits=32)
            ])
        }

    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """Sets the fixed command."""
        output_group = outputs["root_command"]
        # [vel_x, vel_y, rot_vel_z, hip_height]
        cmd = np.array([0.0, 0.0, 0.0, self._config.hip_height], dtype=np.float32)
        output_group[0] = cmd


@dataclass
class LocomotionRootCmdRetargeterConfig:
    """Configuration for locomotion root command retargeter."""
    initial_hip_height: float = 0.72
    movement_scale: float = 0.5
    rotation_scale: float = 0.35
    dt: float = 1.0 / 60.0  # Assumed time step if not provided externally


class LocomotionRootCmdRetargeter(BaseRetargeter):
    """
    Provides root velocity and hip height commands for locomotion based on controller inputs.

    Mapping:
    - Left Controller Thumbstick: Linear velocity (X, Y)
    - Right Controller Thumbstick X: Angular velocity (Z)
    - Right Controller Thumbstick Y: Hip height adjustment
    """

    def __init__(self, config: LocomotionRootCmdRetargeterConfig, name: str) -> None:
        super().__init__(name=name)
        self._config = config
        self._hip_height = config.initial_hip_height

    def input_spec(self) -> RetargeterIO:
        """Requires left and right controller inputs."""
        return {
            "controller_left": ControllerInput(),
            "controller_right": ControllerInput()
        }

    def output_spec(self) -> RetargeterIO:
        """Outputs a 4D root command vector [vel_x, vel_y, rot_vel_z, hip_height]."""
        return {
            "root_command": TensorGroupType("root_command", [
                NDArrayType("command", shape=(4,), dtype=DLDataType.FLOAT, dtype_bits=32)
            ])
        }

    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """Computes root command from controller inputs."""
        left_thumbstick_x = 0.0
        left_thumbstick_y = 0.0
        right_thumbstick_x = 0.0
        right_thumbstick_y = 0.0

        # Process Left Controller
        if "controller_left" in inputs:
            left_ctrl = inputs["controller_left"]
            # Check is_active
            if left_ctrl[ControllerInputIndex.IS_ACTIVE]:
                left_thumbstick_x = float(left_ctrl[ControllerInputIndex.THUMBSTICK_X])  # thumbstick_x
                left_thumbstick_y = float(left_ctrl[ControllerInputIndex.THUMBSTICK_Y])  # thumbstick_y

        # Process Right Controller
        if "controller_right" in inputs:
            right_ctrl = inputs["controller_right"]
            # Check is_active
            if right_ctrl[ControllerInputIndex.IS_ACTIVE]:
                right_thumbstick_x = float(right_ctrl[ControllerInputIndex.THUMBSTICK_X])  # thumbstick_x
                right_thumbstick_y = float(right_ctrl[ControllerInputIndex.THUMBSTICK_Y])  # thumbstick_y

        # Scale inputs
        # Note: In IsaacLab implementation:
        # left_thumbstick_y is forward/backward -> maps to X velocity (negated because up on stick is +1, robot forward is +X)
        # left_thumbstick_x is left/right -> maps to Y velocity (negated because right on stick is +1, robot left is +Y)
        # Wait, IsaacLab says:
        # "left_thumbstick_y is forward/backward, so it maps to X velocity (negated because up is +1)"
        # "left_thumbstick_x is left/right, so it maps to Y velocity (negated because right is +1)"

        # Scaling
        scaled_left_x = left_thumbstick_x * self._config.movement_scale
        scaled_left_y = left_thumbstick_y * self._config.movement_scale

        # Update hip height
        # Right stick Y controls height change
        dt = self._config.dt
        self._hip_height -= right_thumbstick_y * dt * self._config.rotation_scale
        self._hip_height = max(0.4, min(1.0, self._hip_height))

        # Construct command
        # [vel_x, vel_y, rot_vel_z, hip_height]
        # vel_x = -left_stick_y
        # vel_y = -left_stick_x
        # rot_vel_z = -right_stick_x

        cmd = np.array([
            -scaled_left_y,
            -scaled_left_x,
            -right_thumbstick_x,
            self._hip_height
        ], dtype=np.float32)

        outputs["root_command"][0] = cmd

