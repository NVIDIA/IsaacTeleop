# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
SE3 Retargeter Module.

Retargets hand/controller tracking data to end-effector commands using absolute or relative positioning.
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from ..interface.tensor_group_type import TensorGroupType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import (
    HandInput,
    ControllerInput,
    NDArrayType,
    DLDataType,
    HandInputIndex,
    ControllerInputIndex,
    HandJointIndex,
)

try:
    from scipy.spatial.transform import Rotation, Slerp  # type: ignore
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


@dataclass
class Se3RetargeterConfig:
    """Configuration for SE3 retargeters."""
    input_device: str = "hand_right"  # "hand_left", "hand_right", "controller_left", "controller_right"
    zero_out_xy_rotation: bool = True
    use_wrist_rotation: bool = False
    use_wrist_position: bool = True

    # Abs specific
    target_offset_pos: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    target_offset_rot: Tuple[float, float, float, float] = (0.7071068, 0.7071068, 0.0, 0.0) # w, x, y, z

    # Rel specific
    delta_pos_scale_factor: float = 10.0
    delta_rot_scale_factor: float = 10.0
    alpha_pos: float = 0.5
    alpha_rot: float = 0.5


class Se3AbsRetargeter(BaseRetargeter):
    """
    Retargets tracking data to end-effector commands using absolute positioning.

    Outputs a 7D pose (position [x,y,z] + orientation quaternion [w,x,y,z]).
    """

    def __init__(self, config: Se3RetargeterConfig, name: str) -> None:
        self._config = config
        super().__init__(name=name)
        if not SCIPY_AVAILABLE:
            raise ImportError("scipy is required for Se3AbsRetargeter")

        # Store offsets
        self._target_offset_pos = np.array(config.target_offset_pos)
        # Convert w,x,y,z (Isaac Lab) to x,y,z,w (scipy)
        self._target_offset_rot = np.array([*config.target_offset_rot[1:], config.target_offset_rot[0]])

        # Initialize last pose (pos: 0,0,0, rot: 1,0,0,0 wxyz)
        self._last_pose = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def input_spec(self) -> RetargeterIOType:
        if "hand" in self._config.input_device:
            return {self._config.input_device: HandInput()}
        elif "controller" in self._config.input_device:
            return {self._config.input_device: ControllerInput()}
        else:
            raise ValueError(f"Unknown input device: {self._config.input_device}")

    def output_spec(self) -> RetargeterIOType:
        return {
            "ee_pose": TensorGroupType("ee_pose", [
                NDArrayType("pose", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32)
            ])
        }

    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        device_name = self._config.input_device
        if device_name not in inputs:
            outputs["ee_pose"][0] = self._last_pose
            return

        inp = inputs[device_name]

        wrist = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]) # x,y,z, w,x,y,z

        thumb_tip = None
        index_tip = None
        active = False

        if "hand" in device_name:
            # Hand Input
            # Check active
            if inp[HandInputIndex.IS_ACTIVE]: # is_active
                active = True
                joint_positions = np.from_dlpack(inp[HandInputIndex.JOINT_POSITIONS])
                joint_orientations = np.from_dlpack(inp[HandInputIndex.JOINT_ORIENTATIONS])
                joint_valid = np.from_dlpack(inp[HandInputIndex.JOINT_VALID])

                # Wrist = 1
                if joint_valid[HandJointIndex.WRIST]:
                    wrist_pos = joint_positions[HandJointIndex.WRIST]
                    wrist_ori = joint_orientations[HandJointIndex.WRIST] # WXYZ
                    wrist = np.concatenate([wrist_pos, wrist_ori])

                if joint_valid[HandJointIndex.THUMB_TIP]: thumb_tip = np.concatenate([joint_positions[HandJointIndex.THUMB_TIP], joint_orientations[HandJointIndex.THUMB_TIP]])
                if joint_valid[HandJointIndex.INDEX_TIP]: index_tip = np.concatenate([joint_positions[HandJointIndex.INDEX_TIP], joint_orientations[HandJointIndex.INDEX_TIP]])

        else:
            # Controller Input
            # Check active
            if inp[ControllerInputIndex.IS_ACTIVE]: # is_active
                active = True
                # Grip Pose
                grip_pos = np.from_dlpack(inp[ControllerInputIndex.GRIP_POSITION])
                grip_ori = np.from_dlpack(inp[ControllerInputIndex.GRIP_ORIENTATION]) # WXYZ
                wrist = np.concatenate([grip_pos, grip_ori])

        if not active:
            outputs["ee_pose"][0] = self._last_pose
            return

        # Logic from IsaacLab

        # Get position
        if self._config.use_wrist_position or thumb_tip is None or index_tip is None:
            position = wrist[:3]
        else:
            position = (thumb_tip[:3] + index_tip[:3]) / 2

        # Get rotation
        if self._config.use_wrist_rotation or thumb_tip is None or index_tip is None:
            # wrist is w,x,y,z but scipy expects x,y,z,w
            base_rot = Rotation.from_quat([*wrist[4:], wrist[3]])
        else:
            # thumb_tip is w,x,y,z but scipy expects x,y,z,w
            r0 = Rotation.from_quat([*thumb_tip[4:], thumb_tip[3]])
            r1 = Rotation.from_quat([*index_tip[4:], index_tip[3]])
            key_times = [0, 1]
            slerp = Slerp(key_times, Rotation.concatenate([r0, r1]))
            base_rot = slerp([0.5])[0]

        # Apply offset rotation
        offset_rot = Rotation.from_quat(self._target_offset_rot)
        final_rot = base_rot * offset_rot

        # Apply position offset in the wrist frame
        position = position + base_rot.apply(self._target_offset_pos)

        if self._config.zero_out_xy_rotation:
            z, y, x = final_rot.as_euler("ZYX")
            y = 0.0
            x = 0.0
            final_rot = Rotation.from_euler("ZYX", [z, y, x]) * Rotation.from_euler("X", np.pi, degrees=False)

        # Convert back to w,x,y,z format
        quat = final_rot.as_quat() # x,y,z,w
        rotation = np.array([quat[3], quat[0], quat[1], quat[2]])

        final_pose = np.concatenate([position, rotation]).astype(np.float32)
        self._last_pose = final_pose
        outputs["ee_pose"][0] = final_pose


class Se3RelRetargeter(BaseRetargeter):
    """
    Retargets tracking data to end-effector commands using relative positioning.

    Outputs a 6D delta pose (position delta [x,y,z] + rotation vector [rx,ry,rz]).
    """

    def __init__(self, config: Se3RetargeterConfig, name: str) -> None:
        self._config = config
        super().__init__(name=name)
        if not SCIPY_AVAILABLE:
            raise ImportError("scipy is required for Se3RelRetargeter")

        self._smoothed_delta_pos = np.zeros(3)
        self._smoothed_delta_rot = np.zeros(3)

        self._position_threshold = 0.001
        self._rotation_threshold = 0.01

        self._previous_thumb_tip: Optional[np.ndarray] = None
        self._previous_index_tip: Optional[np.ndarray] = None
        self._previous_wrist = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0])

        self._first_frame = True

    def input_spec(self) -> RetargeterIOType:
        if "hand" in self._config.input_device:
            return {self._config.input_device: HandInput()}
        elif "controller" in self._config.input_device:
            return {self._config.input_device: ControllerInput()}
        else:
            raise ValueError(f"Unknown input device: {self._config.input_device}")

    def output_spec(self) -> RetargeterIOType:
        return {
            "ee_delta": TensorGroupType("ee_delta", [
                NDArrayType("delta", shape=(6,), dtype=DLDataType.FLOAT, dtype_bits=32)
            ])
        }

    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        device_name = self._config.input_device
        if device_name not in inputs:
            return

        inp = inputs[device_name]

        wrist = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0])
        thumb_tip = None
        index_tip = None

        active = False

        if "hand" in device_name:
            if inp[HandInputIndex.IS_ACTIVE]: # is_active
                active = True
                joint_positions = np.from_dlpack(inp[HandInputIndex.JOINT_POSITIONS])
                joint_orientations = np.from_dlpack(inp[HandInputIndex.JOINT_ORIENTATIONS])

                wrist = np.concatenate([joint_positions[HandJointIndex.WRIST], joint_orientations[HandJointIndex.WRIST]])
                thumb_tip = np.concatenate([joint_positions[HandJointIndex.THUMB_TIP], joint_orientations[HandJointIndex.THUMB_TIP]])
                index_tip = np.concatenate([joint_positions[HandJointIndex.INDEX_TIP], joint_orientations[HandJointIndex.INDEX_TIP]])
        else:
            if inp[ControllerInputIndex.IS_ACTIVE]: # is_active
                active = True
                grip_pos = np.from_dlpack(inp[ControllerInputIndex.GRIP_POSITION])
                grip_ori = np.from_dlpack(inp[ControllerInputIndex.GRIP_ORIENTATION])
                wrist = np.concatenate([grip_pos, grip_ori])

        if not active:
             outputs["ee_delta"][0] = np.zeros(6, dtype=np.float32)
             return

        if self._first_frame:
            self._previous_wrist = wrist
            self._previous_thumb_tip = thumb_tip
            self._previous_index_tip = index_tip
            self._first_frame = False
            outputs["ee_delta"][0] = np.zeros(6, dtype=np.float32)
            return

        # Calculate Deltas
        delta_thumb_tip = None
        if thumb_tip is not None and self._previous_thumb_tip is not None:
            delta_thumb_tip = self._calculate_delta_pose(thumb_tip, self._previous_thumb_tip)

        delta_index_tip = None
        if index_tip is not None and self._previous_index_tip is not None:
            delta_index_tip = self._calculate_delta_pose(index_tip, self._previous_index_tip)

        delta_wrist = self._calculate_delta_pose(wrist, self._previous_wrist)

        # Retarget Rel

        # Position
        if self._config.use_wrist_position or delta_thumb_tip is None or delta_index_tip is None:
            position = delta_wrist[:3]
        else:
            position = (delta_thumb_tip[:3] + delta_index_tip[:3]) / 2

        # Rotation
        if self._config.use_wrist_rotation or delta_thumb_tip is None or delta_index_tip is None:
            rotation = delta_wrist[3:6]
        else:
            rotation = (delta_thumb_tip[3:6] + delta_index_tip[3:6]) / 2

        # Zero out XY
        if self._config.zero_out_xy_rotation:
            rotation[0] = 0
            rotation[1] = 0

        # Smooth Position
        self._smoothed_delta_pos = self._config.alpha_pos * position + (1 - self._config.alpha_pos) * self._smoothed_delta_pos
        if np.linalg.norm(self._smoothed_delta_pos) < self._position_threshold:
            self._smoothed_delta_pos = np.zeros(3)
        position = self._smoothed_delta_pos * self._config.delta_pos_scale_factor

        # Smooth Rotation
        self._smoothed_delta_rot = self._config.alpha_rot * rotation + (1 - self._config.alpha_rot) * self._smoothed_delta_rot
        if np.linalg.norm(self._smoothed_delta_rot) < self._rotation_threshold:
            self._smoothed_delta_rot = np.zeros(3)
        rotation = self._smoothed_delta_rot * self._config.delta_rot_scale_factor

        # Update previous
        self._previous_wrist = wrist
        self._previous_thumb_tip = thumb_tip
        self._previous_index_tip = index_tip

        outputs["ee_delta"][0] = np.concatenate([position, rotation]).astype(np.float32)

    def _calculate_delta_pose(self, joint_pose: np.ndarray, previous_joint_pose: np.ndarray) -> np.ndarray:
        delta_pos = joint_pose[:3] - previous_joint_pose[:3]
        # w,x,y,z -> x,y,z,w
        abs_rotation = Rotation.from_quat([*joint_pose[4:7], joint_pose[3]])
        previous_rot = Rotation.from_quat([*previous_joint_pose[4:7], previous_joint_pose[3]])
        relative_rotation = abs_rotation * previous_rot.inv()
        return np.concatenate([delta_pos, relative_rotation.as_rotvec()])

