# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Retargeting Modules.

This module contains retargeters available in TeleopCore.
Many of these are adapted from IsaacLab (Isaac Sim).

Available Retargeters:
    - DexHandRetargeter: Uses dex_retargeting library for accurate hand tracking
    - DexBiManualRetargeter: Bimanual version of DexHandRetargeter
    - TriHandMotionController: Maps VR controller inputs to G1 TriHand joints
    - TriHandBiManualMotionController: Bimanual version of TriHandMotionController
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

from .G1.trihand_motion_controller import (
    TriHandMotionController,
    TriHandBiManualMotionController,
    TriHandMotionControllerConfig,
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
    "TriHandMotionController",
    "TriHandBiManualMotionController",
    "TriHandMotionControllerConfig",

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
