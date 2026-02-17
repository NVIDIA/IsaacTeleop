# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
SE3 Retargeter Module.

Retargets hand/controller tracking data to end-effector commands using absolute or relative positioning.
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional

from ..interface import (
    BaseRetargeter,
    ParameterState,
    RetargeterIOType,
)
from ..interface.tunable_parameter import BoolParameter, VectorParameter
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
    from scipy.spatial.transform import Rotation, Slerp
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

    # Abs specific - Position offset (meters)
    target_offset_x: float = 0.0
    target_offset_y: float = 0.0
    target_offset_z: float = 0.0

    # Abs specific - Rotation offset (degrees, applied as intrinsic XYZ Euler angles)
    target_offset_roll: float = 90.0    # rotation about X axis
    target_offset_pitch: float = 0.0    # rotation about Y axis
    target_offset_yaw: float = 0.0      # rotation about Z axis

    # Rel specific
    delta_pos_scale_factor: float = 10.0
    delta_rot_scale_factor: float = 10.0
    alpha_pos: float = 0.5
    alpha_rot: float = 0.5

    # Optional path for persisting tuned parameter values to JSON
    parameter_config_path: Optional[str] = None


class Se3AbsRetargeter(BaseRetargeter):
    """
    Retargets tracking data to end-effector commands using absolute positioning.

    Outputs a 7D pose (position [x,y,z] + orientation quaternion [x,y,z,w]).
    """

    def __init__(self, config: Se3RetargeterConfig, name: str) -> None:
        self._config = config
        if not SCIPY_AVAILABLE:
            raise ImportError("scipy is required for Se3AbsRetargeter")

        # Build position offset from individual x/y/z components
        self._target_offset_pos = np.array([
            config.target_offset_x,
            config.target_offset_y,
            config.target_offset_z,
        ])
        # Build rotation offset quaternion (x,y,z,w) from roll/pitch/yaw Euler angles
        self._target_offset_rot = Rotation.from_euler(
            "XYZ",
            [config.target_offset_roll, config.target_offset_pitch, config.target_offset_yaw],
            degrees=True,
        ).as_quat()  # returns x,y,z,w (scipy convention)

        # Initialize last pose (pos: 0,0,0, rot: identity xyzw)
        self._last_pose = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0], dtype=np.float32)

        # Build tunable parameters for the UI
        rotation_offset_param = VectorParameter(
            name="rotation_offset_rpy",
            description="Rotation offset (Roll, Pitch, Yaw in degrees)",
            element_names=["roll", "pitch", "yaw"],
            default_value=np.array([config.target_offset_roll, config.target_offset_pitch, config.target_offset_yaw],
                                   dtype=np.float32),
            min_value=-180.0,
            max_value=180.0,
            sync_fn=self._update_rotation_offset,
        )

        position_offset_param = VectorParameter(
            name="position_offset_xyz",
            description="Position offset (X, Y, Z in meters)",
            element_names=["x", "y", "z"],
            default_value=np.array([config.target_offset_x, config.target_offset_y, config.target_offset_z],
                                   dtype=np.float32),
            min_value=-2.0,
            max_value=2.0,
            step_size=0.001,
            sync_fn=self._update_position_offset,
        )

        zero_out_xy_param = BoolParameter(
            name="zero_out_xy_rotation",
            description="Zero out X/Y rotation (keep only yaw)",
            default_value=config.zero_out_xy_rotation,
            sync_fn=lambda v: setattr(self._config, "zero_out_xy_rotation", v),
        )

        use_wrist_rotation_param = BoolParameter(
            name="use_wrist_rotation",
            description="Use wrist rotation instead of fingertip average",
            default_value=config.use_wrist_rotation,
            sync_fn=lambda v: setattr(self._config, "use_wrist_rotation", v),
        )

        use_wrist_position_param = BoolParameter(
            name="use_wrist_position",
            description="Use wrist position instead of fingertip average",
            default_value=config.use_wrist_position,
            sync_fn=lambda v: setattr(self._config, "use_wrist_position", v),
        )

        param_state = ParameterState(
            name,
            parameters=[
                rotation_offset_param,
                position_offset_param,
                zero_out_xy_param,
                use_wrist_rotation_param,
                use_wrist_position_param,
            ],
            config_file=config.parameter_config_path,
        )

        super().__init__(name=name, parameter_state=param_state)

    def _update_rotation_offset(self, rpy) -> None:
        """Sync function: recompute rotation offset quaternion from RPY (degrees)."""
        self._target_offset_rot = Rotation.from_euler(
            "XYZ", list(rpy), degrees=True
        ).as_quat()

    def _update_position_offset(self, xyz) -> None:
        """Sync function: update position offset vector."""
        self._target_offset_pos = np.array(xyz, dtype=np.float64)

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

        wrist = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]) # x,y,z, qx,qy,qz,qw

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
                    wrist_ori = joint_orientations[HandJointIndex.WRIST] # XYZW
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
                grip_ori = np.from_dlpack(inp[ControllerInputIndex.GRIP_ORIENTATION]) # XYZW
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
            # wrist quat is already x,y,z,w (scipy convention) at indices 3:7
            base_rot = Rotation.from_quat(wrist[3:7])
        else:
            # thumb_tip/index_tip quats are already x,y,z,w at indices 3:7
            r0 = Rotation.from_quat(thumb_tip[3:7])
            r1 = Rotation.from_quat(index_tip[3:7])
            key_times = [0, 1]
            slerp = Slerp(key_times, Rotation.concatenate([r0, r1]))
            base_rot = slerp([0.5])[0]

        # Apply offset rotation
        offset_rot = Rotation.from_quat(self._target_offset_rot)
        final_rot = base_rot * offset_rot

        # Apply position offset in the wrist frame
        position = position + base_rot.apply(self._target_offset_pos)

        if self._config.zero_out_xy_rotation:
            z, _, _ = final_rot.as_euler("ZYX")
            final_rot = Rotation.from_euler("ZYX", np.array([z, 0.0, 0.0])) * Rotation.from_euler("X", np.pi, degrees=False)

        # as_quat() returns x,y,z,w which matches our convention
        rotation = final_rot.as_quat()

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

        self._smoothed_delta_pos: np.ndarray = np.zeros(3)
        self._smoothed_delta_rot: np.ndarray = np.zeros(3)

        self._position_threshold = 0.001
        self._rotation_threshold = 0.01

        self._previous_thumb_tip: Optional[np.ndarray] = None
        self._previous_index_tip: Optional[np.ndarray] = None
        self._previous_wrist = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])

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

        wrist = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
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
        # Quat at indices 3:7 is already x,y,z,w (scipy convention)
        abs_rotation = Rotation.from_quat(joint_pose[3:7])
        previous_rot = Rotation.from_quat(previous_joint_pose[3:7])
        relative_rotation = abs_rotation * previous_rot.inv()
        return np.concatenate([delta_pos, relative_rotation.as_rotvec()])

