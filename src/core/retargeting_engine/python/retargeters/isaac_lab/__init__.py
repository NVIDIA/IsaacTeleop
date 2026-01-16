# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
IsaacLab Examples - Retargeters ported from IsaacLab.

This module contains retargeters originally from IsaacLab (Isaac Sim),
adapted to work with TeleopCore's retargeting framework.

Available Retargeters:
    - DexHandRetargeter: Uses dex_retargeting library for accurate hand tracking
    - DexBiManualRetargeter: Bimanual version of DexHandRetargeter
    - DexMotionController: Maps VR controller inputs to dexterous hand joints
    - DexBiManualMotionController: Bimanual version of DexMotionController
    - LocomotionFixedRootCmdRetargeter: Fixed root command (standing still)
    - LocomotionRootCmdRetargeter: Locomotion from controller inputs
    - GripperRetargeter: Pinch-based gripper control
    - Se3AbsRetargeter: Absolute EE pose control
    - Se3RelRetargeter: Relative EE delta control
"""

from .dex_hand_retargeter import (
    DexHandRetargeter,
    DexBiManualRetargeter,
    DexHandRetargeterConfig,
)

from .dex_motion_controller import (
    DexMotionController,
    DexBiManualMotionController,
    DexMotionControllerConfig,
)

from .locomotion_retargeter import (
    LocomotionFixedRootCmdRetargeter,
    LocomotionFixedRootCmdRetargeterConfig,
    LocomotionRootCmdRetargeter,
    LocomotionRootCmdRetargeterConfig,
)

from .gripper_retargeter import (
    GripperRetargeter,
    GripperRetargeterConfig,
)

from .se3_retargeter import (
    Se3AbsRetargeter,
    Se3RelRetargeter,
    Se3RetargeterConfig,
)

__all__ = [
    # Hand tracking retargeters
    "DexHandRetargeter",
    "DexBiManualRetargeter",
    "DexHandRetargeterConfig",

    # Motion controller retargeters
    "DexMotionController",
    "DexBiManualMotionController",
    "DexMotionControllerConfig",

    # Locomotion retargeters
    "LocomotionFixedRootCmdRetargeter",
    "LocomotionFixedRootCmdRetargeterConfig",
    "LocomotionRootCmdRetargeter",
    "LocomotionRootCmdRetargeterConfig",

    # Manipulator retargeters
    "GripperRetargeter",
    "GripperRetargeterConfig",
    "Se3AbsRetargeter",
    "Se3RelRetargeter",
    "Se3RetargeterConfig",
]
