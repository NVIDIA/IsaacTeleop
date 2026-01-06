# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Standard TensorGroupType definitions for common teleoperation data structures.

These definitions match the FlatBuffers schemas in IsaacTeleop/src/core/schema/fbs/
and provide type-safe specifications for hand tracking, head tracking, and controller data.
"""

from ..interface.tensor_group_type import TensorGroupType
from .scalar_types import FloatType, IntType, BoolType
from .ndarray_types import NDArrayType, DLDataType, DLDeviceType


# Constants
NUM_HAND_JOINTS = 26  # XR_HAND_JOINT_COUNT_EXT from OpenXR

# ============================================================================
# Hand Tracking Types
# ============================================================================

def HandInput() -> TensorGroupType:
    """
    Standard TensorGroupType for hand tracking data.
    
    Matches the HandPose schema from hand.fbs with 26 joints (XR_HAND_JOINT_COUNT_EXT).
    
    The actual left/right distinction comes from the RetargeterIO dictionary key
    (e.g., "hand_left" vs "hand_right"), not from the type itself. Both left and
    right hands use the same type structure.
    
    Fields:
        - joint_positions: (26, 3) float32 array - XYZ positions for each joint
        - joint_orientations: (26, 4) float32 array - WXYZ quaternions for each joint
        - joint_radii: (26,) float32 array - Radius of each joint
        - joint_valid: (26,) bool array - Validity flag for each joint
        - is_active: bool - Whether hand tracking is active
        - timestamp: int - Timestamp in XrTime format (int64)
    
    Returns:
        TensorGroupType for hand tracking data
    
    Schema reference: IsaacTeleop/src/core/schema/fbs/hand.fbs
    
    Example:
        # Left and right hands use the same type, distinguished by dict key
        def input_spec(self) -> RetargeterIO:
            return {
                "hand_left": HandInput(),    # key indicates left hand
                "hand_right": HandInput(),   # key indicates right hand
            }
    """
    return TensorGroupType("hand", [
        NDArrayType(
            "hand_joint_positions",
            shape=(NUM_HAND_JOINTS, 3),
            dtype=DLDataType.FLOAT,
            dtype_bits=32
        ),
        NDArrayType(
            "hand_joint_orientations",
            shape=(NUM_HAND_JOINTS, 4),
            dtype=DLDataType.FLOAT,
            dtype_bits=32
        ),
        NDArrayType(
            "hand_joint_radii",
            shape=(NUM_HAND_JOINTS,),
            dtype=DLDataType.FLOAT,
            dtype_bits=32
        ),
        NDArrayType(
            "hand_joint_valid",
            shape=(NUM_HAND_JOINTS,),
            dtype=DLDataType.UINT,
            dtype_bits=8  # bool represented as uint8
        ),
        BoolType("hand_is_active"),
        IntType("hand_timestamp"),
    ])


# ============================================================================
# Head Tracking Types
# ============================================================================

def HeadPose() -> TensorGroupType:
    """
    Standard TensorGroupType for head tracking data.
    
    Matches the HeadPose schema from head.fbs.
    
    Fields:
        - head_position: (3,) float32 array - XYZ position
        - head_orientation: (4,) float32 array - WXYZ quaternion
        - head_is_valid: bool - Whether head tracking data is valid
        - head_timestamp: int - Timestamp in XrTime format (int64)
    
    Returns:
        TensorGroupType for head tracking data
    
    Schema reference: IsaacTeleop/src/core/schema/fbs/head.fbs
    """
    return TensorGroupType("head", [
        NDArrayType(
            "head_position",
            shape=(3,),
            dtype=DLDataType.FLOAT,
            dtype_bits=32
        ),
        NDArrayType(
            "head_orientation",
            shape=(4,),
            dtype=DLDataType.FLOAT,
            dtype_bits=32
        ),
        BoolType("head_is_valid"),
        IntType("head_timestamp"),
    ])


# ============================================================================
# Controller Types
# ============================================================================

def ControllerInput() -> TensorGroupType:
    """
    Standard TensorGroupType for VR controller data.
    
    Provides grip pose, aim pose, and all controller inputs (buttons, triggers, thumbstick).
    
    The actual left/right distinction comes from the RetargeterIO dictionary key
    (e.g., "controller_left" vs "controller_right"), not from the type itself. Both
    left and right controllers use the same type structure.
    
    Fields:
        - grip_position: (3,) float32 array - XYZ position of grip pose
        - grip_orientation: (4,) float32 array - WXYZ quaternion of grip pose
        - aim_position: (3,) float32 array - XYZ position of aim pose
        - aim_orientation: (4,) float32 array - WXYZ quaternion of aim pose
        - primary_click: float - Primary button (e.g., A/X button) [0.0-1.0]
        - secondary_click: float - Secondary button (e.g., B/Y button) [0.0-1.0]
        - thumbstick_x: float - Thumbstick X axis [-1.0 to 1.0]
        - thumbstick_y: float - Thumbstick Y axis [-1.0 to 1.0]
        - thumbstick_click: float - Thumbstick button press [0.0-1.0]
        - squeeze_value: float - Grip/squeeze trigger [0.0-1.0]
        - trigger_value: float - Index finger trigger [0.0-1.0]
        - is_active: bool - Whether controller is tracked/active
    
    Returns:
        TensorGroupType for controller data
    
    Example:
        # Left and right controllers use the same type, distinguished by dict key
        def input_spec(self) -> RetargeterIO:
            return {
                "controller_left": ControllerInput(),    # key indicates left controller
                "controller_right": ControllerInput(),   # key indicates right controller
            }
    """
    return TensorGroupType("controller", [
        NDArrayType(
            "controller_grip_position",
            shape=(3,),
            dtype=DLDataType.FLOAT,
            dtype_bits=32
        ),
        NDArrayType(
            "controller_grip_orientation",
            shape=(4,),
            dtype=DLDataType.FLOAT,
            dtype_bits=32
        ),
        NDArrayType(
            "controller_aim_position",
            shape=(3,),
            dtype=DLDataType.FLOAT,
            dtype_bits=32
        ),
        NDArrayType(
            "controller_aim_orientation",
            shape=(4,),
            dtype=DLDataType.FLOAT,
            dtype_bits=32
        ),
        FloatType("controller_primary_click"),
        FloatType("controller_secondary_click"),
        FloatType("controller_thumbstick_x"),
        FloatType("controller_thumbstick_y"),
        FloatType("controller_thumbstick_click"),
        FloatType("controller_squeeze_value"),
        FloatType("controller_trigger_value"),
        BoolType("controller_is_active"),
    ])

