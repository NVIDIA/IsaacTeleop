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

Configuration Classes:
    - DexHandRetargeterConfig: Configuration for DexHandRetargeter
    - DexMotionControllerConfig: Configuration for DexMotionController
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

__all__ = [
    # Hand tracking retargeters
    "DexHandRetargeter",
    "DexBiManualRetargeter",
    "DexHandRetargeterConfig",
    
    # Motion controller retargeters
    "DexMotionController",
    "DexBiManualMotionController",
    "DexMotionControllerConfig",
]

