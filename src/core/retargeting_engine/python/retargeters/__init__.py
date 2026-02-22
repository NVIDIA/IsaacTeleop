# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Retargeting Modules.

This module contains retargeters available in Isaac Teleop.
Many of these are adapted from IsaacLab (Isaac Sim).

Available Retargeters:
    - DexHandRetargeter: Uses dex_retargeting library for accurate hand tracking
    - DexBiManualRetargeter: Bimanual version of DexHandRetargeter
    - TriHandMotionControllerRetargeter: Maps VR controller inputs to G1 TriHand joints
    - TriHandBiManualMotionControllerRetargeter: Bimanual version of TriHandMotionControllerRetargeter
    - LocomotionFixedRootCmdRetargeter: Fixed root command (standing still)
    - LocomotionRootCmdRetargeter: Locomotion from controller inputs
    - FootPedalRootCmdRetargeter: Root command from 3-axis foot pedal (horizontal/vertical + rudder)
    - GripperRetargeter: Pinch-based gripper control
    - Se3AbsRetargeter: Absolute EE pose control
    - Se3RelRetargeter: Relative EE delta control
    - TensorReorderer: Reorders and flattens multiple inputs into a single tensor
"""

from .dex_hand_retargeter import (
    DexHandRetargeter,
    DexBiManualRetargeter,
    DexHandRetargeterConfig,
)

from .G1.trihand_motion_controller import (
    TriHandMotionControllerRetargeter,
    TriHandBiManualMotionControllerRetargeter,
    TriHandMotionControllerConfig,
)

from .locomotion_retargeter import (
    LocomotionFixedRootCmdRetargeter,
    LocomotionFixedRootCmdRetargeterConfig,
    LocomotionRootCmdRetargeter,
    LocomotionRootCmdRetargeterConfig,
)

from .foot_pedal_retargeter import (
    FootPedalRootCmdRetargeter,
    FootPedalRootCmdRetargeterConfig,
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

from .tensor_reorderer import TensorReorderer

__all__ = [
    # Hand tracking retargeters
    "DexHandRetargeter",
    "DexBiManualRetargeter",
    "DexHandRetargeterConfig",
    # Motion controller retargeters
    "TriHandMotionControllerRetargeter",
    "TriHandBiManualMotionControllerRetargeter",
    "TriHandMotionControllerConfig",
    # Locomotion retargeters
    "LocomotionFixedRootCmdRetargeter",
    "LocomotionFixedRootCmdRetargeterConfig",
    "LocomotionRootCmdRetargeter",
    "LocomotionRootCmdRetargeterConfig",
    "FootPedalRootCmdRetargeter",
    "FootPedalRootCmdRetargeterConfig",
    # Manipulator retargeters
    "GripperRetargeter",
    "GripperRetargeterConfig",
    "Se3AbsRetargeter",
    "Se3RelRetargeter",
    "Se3RetargeterConfig",
    # Utility retargeters
    "TensorReorderer",
]
