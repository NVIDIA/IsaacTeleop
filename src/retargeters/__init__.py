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
    - SharpaHandRetargeter: Pinocchio/Pink IK-based retargeting for Sharpa hand
    - SharpaBiManualRetargeter: Bimanual version of SharpaHandRetargeter
    - Se3AbsRetargeter: Absolute EE pose control
    - Se3RelRetargeter: Relative EE delta control
    - TensorReorderer: Reorders and flattens multiple inputs into a single tensor
"""

import importlib as _importlib

# All retargeters are lazy-loaded so that importing this package has zero
# side-effects and does not require any optional dependencies to be installed.
# Each name is resolved on first access via __getattr__.
#
# Entries: name -> (module_path, attr, pip_extra_or_None)
_LAZY_IMPORTS: dict[str, tuple[str, str, str | None]] = {
    # .dex_hand_retargeter  (requires retargeters extra: nlopt, torch, …)
    "DexHandRetargeter": (".dex_hand_retargeter", "DexHandRetargeter", "retargeters"),
    "DexBiManualRetargeter": (
        ".dex_hand_retargeter",
        "DexBiManualRetargeter",
        "retargeters",
    ),
    "DexHandRetargeterConfig": (
        ".dex_hand_retargeter",
        "DexHandRetargeterConfig",
        "retargeters",
    ),
    # .G1.trihand_motion_controller
    "TriHandMotionControllerRetargeter": (
        ".G1.trihand_motion_controller",
        "TriHandMotionControllerRetargeter",
        None,
    ),
    "TriHandBiManualMotionControllerRetargeter": (
        ".G1.trihand_motion_controller",
        "TriHandBiManualMotionControllerRetargeter",
        None,
    ),
    "TriHandMotionControllerConfig": (
        ".G1.trihand_motion_controller",
        "TriHandMotionControllerConfig",
        None,
    ),
    # .locomotion_retargeter
    "LocomotionFixedRootCmdRetargeter": (
        ".locomotion_retargeter",
        "LocomotionFixedRootCmdRetargeter",
        None,
    ),
    "LocomotionFixedRootCmdRetargeterConfig": (
        ".locomotion_retargeter",
        "LocomotionFixedRootCmdRetargeterConfig",
        None,
    ),
    "LocomotionRootCmdRetargeter": (
        ".locomotion_retargeter",
        "LocomotionRootCmdRetargeter",
        None,
    ),
    "LocomotionRootCmdRetargeterConfig": (
        ".locomotion_retargeter",
        "LocomotionRootCmdRetargeterConfig",
        None,
    ),
    # .foot_pedal_retargeter
    "FootPedalRootCmdRetargeter": (
        ".foot_pedal_retargeter",
        "FootPedalRootCmdRetargeter",
        None,
    ),
    "FootPedalRootCmdRetargeterConfig": (
        ".foot_pedal_retargeter",
        "FootPedalRootCmdRetargeterConfig",
        None,
    ),
    # .gripper_retargeter
    "GripperRetargeter": (".gripper_retargeter", "GripperRetargeter", None),
    "GripperRetargeterConfig": (".gripper_retargeter", "GripperRetargeterConfig", None),
    # .se3_retargeter  (requires retargeters-lite extra: scipy)
    "Se3AbsRetargeter": (".se3_retargeter", "Se3AbsRetargeter", "retargeters-lite"),
    "Se3RelRetargeter": (".se3_retargeter", "Se3RelRetargeter", "retargeters-lite"),
    "Se3RetargeterConfig": (
        ".se3_retargeter",
        "Se3RetargeterConfig",
        "retargeters-lite",
    ),
    # .sharpa_hand_retargeter  (requires grounding extra: robotic_grounding,
    # which transitively pulls pinocchio, pink, etc.)
    "SharpaHandRetargeter": (
        ".sharpa_hand_retargeter",
        "SharpaHandRetargeter",
        "grounding",
    ),
    "SharpaBiManualRetargeter": (
        ".sharpa_hand_retargeter",
        "SharpaBiManualRetargeter",
        "grounding",
    ),
    "SharpaHandRetargeterConfig": (
        ".sharpa_hand_retargeter",
        "SharpaHandRetargeterConfig",
        "grounding",
    ),
    # .tensor_reorderer
    "TensorReorderer": (".tensor_reorderer", "TensorReorderer", None),
}


def __getattr__(name: str):
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_path, attr, extra = _LAZY_IMPORTS[name]
    try:
        mod = _importlib.import_module(module_path, __package__)
    except ModuleNotFoundError as exc:
        if extra is None:
            raise
        raise ModuleNotFoundError(
            f"{name} requires additional dependencies that are not installed.\n"
            f"Install them with:  pip install 'isaacteleop[{extra}]'"
        ) from exc

    value = getattr(mod, attr)
    globals()[name] = value
    return value


__all__ = [
    # Hand tracking retargeters (require retargeters extra)
    "DexHandRetargeter",
    "DexBiManualRetargeter",
    "DexHandRetargeterConfig",
    # Motion controller retargeters
    "TriHandMotionControllerRetargeter",
    "TriHandBiManualMotionControllerRetargeter",
    "TriHandMotionControllerConfig",
    "FootPedalRootCmdRetargeter",
    "FootPedalRootCmdRetargeterConfig",
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
    # Sharpa hand retargeters (require grounding extra: robotic_grounding)
    "SharpaHandRetargeter",
    "SharpaBiManualRetargeter",
    "SharpaHandRetargeterConfig",
    # Utility retargeters
    "TensorReorderer",
]
