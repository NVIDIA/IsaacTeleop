# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Dex Hand Retargeter Module.

Generic retargeter for dexterous hands using the dex_retargeting library.
This module wraps the dex_retargeting library to retarget OpenXR hand tracking data
to robot hand joint angles. It supports configuration via YAML files and URDFs.

Based on IsaacLab's DexHandRetargeter, adapted for TeleopCore's retargeting framework.
"""

import contextlib
import numpy as np
import tempfile
import os
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass

from ..interface.retargeting_module import BaseRetargeter, RetargeterIO
from ..interface.tensor_group_type import TensorGroupType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import HandInput, FloatType, NUM_HAND_JOINTS
from ..tensor_types import HandInputIndex, HandJointIndex

# Try to import yaml for config file handling
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# Try to import scipy for rotation handling
try:
    from scipy.spatial.transform import Rotation as R
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

# Helper to import dex_retargeting which might not be available on all platforms
try:
    from dex_retargeting.retargeting_config import RetargetingConfig
    DEX_RETARGETING_AVAILABLE = True
except ImportError:
    DEX_RETARGETING_AVAILABLE = False


logger = logging.getLogger(__name__)


@dataclass
class DexHandRetargeterConfig:
    """Configuration for the dexterous hand retargeter.

    Attributes:
        hand_joint_names: List of joint names in the robot hand (in order)
        hand_retargeting_config: Path to YAML config file for dex_retargeting
        hand_urdf: Path to URDF file for the robot hand
        handtracking_to_baselink_frame_transform: 3x3 rotation matrix (flattened to 9 elements)
                                                   for transforming from hand tracking to robot base frame.
                                                   Default: G1/Inspire frame (0,0,1, 1,0,0, 0,1,0)
        hand_side: Which hand to retarget ("left" or "right")
    """
    hand_joint_names: List[str]
    hand_retargeting_config: str
    hand_urdf: str
    handtracking_to_baselink_frame_transform: tuple = (0, 0, 1, 1, 0, 0, 0, 1, 0)
    hand_side: str = "left"


class DexHandRetargeter(BaseRetargeter):
    """
    Generic retargeter for dexterous hands using the dex_retargeting library.

    This retargeter wraps the dex_retargeting library to convert OpenXR hand tracking
    data (26 joints with positions and orientations) into robot-specific joint angles.

    Inputs:
        - "hand_{side}": Hand tracking data with 26 joint positions and orientations

    Outputs:
        - "hand_joints": Joint angles for the robot hand (size determined by config)

    The retargeter:
    1. Extracts relevant joints from OpenXR's 26-joint format (maps to 21 joints)
    2. Transforms positions to canonical frame (centered at wrist, rotated by wrist orientation)
    3. Applies coordinate frame transform (handtracking -> robot base frame)
    4. Runs dex_retargeting optimizer to compute robot joint angles
    5. Maps optimized angles to output joint order specified in config
    """

    def __init__(self, config: DexHandRetargeterConfig, name: str) -> None:
        """
        Initialize the dex hand retargeter.

        Args:
            config: Configuration object for the retargeter
            name: Name identifier for this retargeter (must be unique)
        """
        self._config = config
        self._hand_side = config.hand_side.lower()
        if self._hand_side not in ["left", "right"]:
            raise ValueError(f"hand_side must be 'left' or 'right', got: {self._hand_side}")

        self._hand_joint_names = config.hand_joint_names

        super().__init__(name=name)

        # Check dependencies
        if not DEX_RETARGETING_AVAILABLE:
            raise ImportError(
                "The 'dex_retargeting' package is required but not installed. "
                "Install with: pip install dex-retargeting"
            )

        if not SCIPY_AVAILABLE:
            raise ImportError(
                "The 'scipy' package is required but not installed. "
                "Install with: pip install scipy"
            )

        if not YAML_AVAILABLE:
            raise ImportError(
                "The 'pyyaml' package is required but not installed. "
                "Install with: pip install pyyaml"
            )

        # Setup paths and configs
        self._prepare_configs()

        # Initialize dex retargeting optimizer
        self._dex_hand = RetargetingConfig.load_from_file(config.hand_retargeting_config).build()

        # Cache joint names from optimizer
        self._dof_names = self._dex_hand.optimizer.robot.dof_joint_names

        # Store transform
        self._handtracking2baselink = np.array(config.handtracking_to_baselink_frame_transform).reshape(3, 3)

        # Map OpenXR joints (26) to Dex-retargeting (21)
        # OpenXR indices: Wrist(1), Thumb(2-5), Index(7-10), Middle(12-15), Ring(17-20), Pinky(22-25)
        # We skip index 0 (palm) and skip metacarpal joints for non-thumb fingers
        self._hand_joints_index = [
            HandJointIndex.WRIST,
            HandJointIndex.THUMB_METACARPAL, HandJointIndex.THUMB_PROXIMAL, HandJointIndex.THUMB_DISTAL, HandJointIndex.THUMB_TIP,
            HandJointIndex.INDEX_PROXIMAL, HandJointIndex.INDEX_INTERMEDIATE, HandJointIndex.INDEX_DISTAL, HandJointIndex.INDEX_TIP,
            HandJointIndex.MIDDLE_PROXIMAL, HandJointIndex.MIDDLE_INTERMEDIATE, HandJointIndex.MIDDLE_DISTAL, HandJointIndex.MIDDLE_TIP,
            HandJointIndex.RING_PROXIMAL, HandJointIndex.RING_INTERMEDIATE, HandJointIndex.RING_DISTAL, HandJointIndex.RING_TIP,
            HandJointIndex.LITTLE_PROXIMAL, HandJointIndex.LITTLE_INTERMEDIATE, HandJointIndex.LITTLE_DISTAL, HandJointIndex.LITTLE_TIP
        ]

    def input_spec(self) -> RetargeterIO:
        """Define input collections for hand tracking."""
        if self._hand_side == "left":
            return {"hand_left": HandInput()}
        else:
            return {"hand_right": HandInput()}

    def output_spec(self) -> RetargeterIO:
        """Define output collections for robot hand joint angles."""
        return {
            "hand_joints": TensorGroupType(
                f"hand_joints_{self._hand_side}",
                [FloatType(name) for name in self._hand_joint_names]
            )
        }

    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Execute the hand retargeting transformation.

        Args:
            inputs: Dict with hand tracking data
            outputs: Dict with "hand_joints" TensorGroup for robot joint angles
        """
        # Get input hand data
        hand_input_key = f"hand_{self._hand_side}"
        hand_group = inputs[hand_input_key]

        # Check if hand tracking is active
        is_active = hand_group[HandInputIndex.IS_ACTIVE]  # is_active field

        if not is_active:
            # Output zeros if hand tracking is not active
            output_group = outputs["hand_joints"]
            for i in range(len(self._hand_joint_names)):
                output_group[i] = 0.0
            return

        # Convert NDArray inputs to numpy
        joint_positions = np.from_dlpack(hand_group[HandInputIndex.JOINT_POSITIONS])      # (26, 3) float32
        joint_orientations = np.from_dlpack(hand_group[HandInputIndex.JOINT_ORIENTATIONS])   # (26, 4) float32
        joint_valid = np.from_dlpack(hand_group[HandInputIndex.JOINT_VALID])          # (26,) uint8

        # Create poses dictionary (joint positions + orientations)
        # Format: {joint_name: [x, y, z, qw, qx, qy, qz], ...}
        poses = {}

        # Joint names in OpenXR order
        joint_names = [
            "palm", "wrist",
            "thumb_metacarpal", "thumb_proximal", "thumb_distal", "thumb_tip",
            "index_metacarpal", "index_proximal", "index_intermediate", "index_distal", "index_tip",
            "middle_metacarpal", "middle_proximal", "middle_intermediate", "middle_distal", "middle_tip",
            "ring_metacarpal", "ring_proximal", "ring_intermediate", "ring_distal", "ring_tip",
            "little_metacarpal", "little_proximal", "little_intermediate", "little_distal", "little_tip"
        ]

        for i, joint_name in enumerate(joint_names):
            if joint_valid[i] > 0:  # Joint is valid
                pos = joint_positions[i]
                ori = joint_orientations[i]  # WXYZ format
                poses[joint_name] = np.concatenate([pos, ori])

        # Compute retargeting
        q = self._compute_hand(poses)

        # Map to output vector based on configured joint names
        output_group = outputs["hand_joints"]
        for i, name in enumerate(self._dof_names):
            if name in self._hand_joint_names:
                idx = self._hand_joint_names.index(name)
                output_group[idx] = float(q[i])
            else:
                # Joint not in output, skip
                pass

    # -- Internal Helpers --

    def _prepare_configs(self) -> None:
        """Downloads URDFs if needed and updates YAML config files."""
        # For now, assume paths are valid local paths
        # In IsaacLab, this would call retrieve_file_path() to download from URLs
        local_urdf = self._config.hand_urdf

        # Update YAML with correct URDF path
        # Returns path to temporary config file
        temp_config = self._update_yaml(self._config.hand_retargeting_config, local_urdf)

        if temp_config:
            self._config.hand_retargeting_config = temp_config

    def _update_yaml(self, yaml_path: str, urdf_path: str) -> Optional[str]:
        """
        Updates the 'urdf_path' field in the retargeting YAML config.
        Returns path to new temporary config file.
        """
        if not YAML_AVAILABLE:
            logger.warning("yaml not available, cannot update config file")
            return None

        try:
            with open(yaml_path) as f:
                config = yaml.safe_load(f)

            if "retargeting" in config:
                config["retargeting"]["urdf_path"] = urdf_path

                # Write to temp file to avoid modifying original config
                fd, path = tempfile.mkstemp(suffix=".yml", prefix="dex_retarget_")
                with os.fdopen(fd, 'w') as f:
                    yaml.dump(config, f)
                return path

            return None
        except Exception as e:
            logger.error(f"Error updating YAML {yaml_path}: {e}")
            return None

    def _compute_hand(self, poses: Dict[str, np.ndarray]) -> np.ndarray:
        """
        Computes retargeting for a single hand.

        Args:
            poses: Dictionary mapping joint names to pose arrays [x,y,z,qw,qx,qy,qz]

        Returns:
            Array of joint angles for the robot hand
        """
        if not poses or "wrist" not in poses:
            return np.zeros(len(self._dex_hand.optimizer.robot.dof_joint_names))

        # 1. Extract positions for relevant joints (21 joints)
        hand_joints = []
        joint_names = [
            "palm", "wrist",
            "thumb_metacarpal", "thumb_proximal", "thumb_distal", "thumb_tip",
            "index_metacarpal", "index_proximal", "index_intermediate", "index_distal", "index_tip",
            "middle_metacarpal", "middle_proximal", "middle_intermediate", "middle_distal", "middle_tip",
            "ring_metacarpal", "ring_proximal", "ring_intermediate", "ring_distal", "ring_tip",
            "little_metacarpal", "little_proximal", "little_intermediate", "little_distal", "little_tip"
        ]

        for idx in self._hand_joints_index:
            if idx < len(joint_names):
                joint_name = joint_names[idx]
                if joint_name in poses:
                    hand_joints.append(poses[joint_name])
                else:
                    # Missing joint, use zeros
                    hand_joints.append(np.zeros(7))
            else:
                hand_joints.append(np.zeros(7))

        joint_pos = np.zeros((21, 3))
        for i, joint_data in enumerate(hand_joints):
            joint_pos[i] = joint_data[:3]  # Extract position

        # 2. Transform to canonical frame
        # Center at wrist (index 0 of our subset)
        joint_pos = joint_pos - joint_pos[0:1, :]

        # Apply wrist rotation alignment (OpenXR WXYZ -> Scipy XYZW)
        wrist_pose = poses.get("wrist")
        if wrist_pose is None:
            return np.zeros(len(self._dex_hand.optimizer.robot.dof_joint_names))

        xr_wrist_quat = wrist_pose[3:]  # [qw, qx, qy, qz]
        # Convert to scipy format [qx, qy, qz, qw]
        wrist_rot = R.from_quat([xr_wrist_quat[1], xr_wrist_quat[2], xr_wrist_quat[3], xr_wrist_quat[0]]).as_matrix()

        # Apply transformations
        target_pos = joint_pos @ wrist_rot @ self._handtracking2baselink

        # 3. Compute reference value for optimizer
        indices = self._dex_hand.optimizer.target_link_human_indices
        if self._dex_hand.optimizer.retargeting_type == "POSITION":
            ref_value = target_pos[indices, :]
        else:
            origin_indices = indices[0, :]
            task_indices = indices[1, :]
            ref_value = target_pos[task_indices, :] - target_pos[origin_indices, :]

        # 4. Run optimizer
        try:
            import torch
            with torch.enable_grad(), torch.inference_mode(False):
                return self._dex_hand.retarget(ref_value)
        except Exception as e:
            logger.error(f"Error in retargeting: {e}")
            return np.zeros(len(self._dex_hand.optimizer.robot.dof_joint_names))


class DexBiManualRetargeter(BaseRetargeter):
    """
    Wrapper around two DexHandRetargeters to support bimanual retargeting.

    This retargeter instantiates two DexHandRetargeter instances (one for each hand)
    and combines their outputs into a single vector ordered according to target_joint_names.

    Inputs:
        - "hand_left": Left hand tracking data
        - "hand_right": Right hand tracking data

    Outputs:
        - "hand_joints": Combined joint angles for both hands
    """

    def __init__(
        self,
        left_config: DexHandRetargeterConfig,
        right_config: DexHandRetargeterConfig,
        target_joint_names: List[str],
        name: str
    ) -> None:
        """
        Initialize the bimanual retargeter.

        Args:
            left_config: Configuration for left hand retargeter
            right_config: Configuration for right hand retargeter
            target_joint_names: Ordered list of joint names for combined output
            name: Name identifier for this retargeter (must be unique)
        """
        self._target_joint_names = target_joint_names

        super().__init__(name=name)

        # Ensure configs have correct hand sides
        left_config.hand_side = "left"
        right_config.hand_side = "right"

        # Create individual retargeters
        self._left_retargeter = DexHandRetargeter(left_config, name=f"{name}_left")
        self._right_retargeter = DexHandRetargeter(right_config, name=f"{name}_right")

        # Prepare index mapping for fast runtime reordering
        self._left_indices = []
        self._right_indices = []
        self._output_indices_left = []
        self._output_indices_right = []

        left_joints = left_config.hand_joint_names
        right_joints = right_config.hand_joint_names

        for i, name in enumerate(target_joint_names):
            if name in left_joints:
                self._output_indices_left.append(i)
                self._left_indices.append(left_joints.index(name))
            elif name in right_joints:
                self._output_indices_right.append(i)
                self._right_indices.append(right_joints.index(name))

    def input_spec(self) -> RetargeterIO:
        """Define input collections for both hands."""
        return {
            "hand_left": HandInput(),
            "hand_right": HandInput()
        }

    def output_spec(self) -> RetargeterIO:
        """Define output collections for combined hand joints."""
        return {
            "hand_joints": TensorGroupType(
                "hand_joints_bimanual",
                [FloatType(name) for name in self._target_joint_names]
            )
        }

    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Execute bimanual hand retargeting.

        Args:
            inputs: Dict with "hand_left" and "hand_right" tracking data
            outputs: Dict with "hand_joints" combined output
        """
        # Create temporary output groups for individual retargeters
        left_outputs = {
            "hand_joints": TensorGroup(self._left_retargeter.output_spec()["hand_joints"])
        }
        right_outputs = {
            "hand_joints": TensorGroup(self._right_retargeter.output_spec()["hand_joints"])
        }

        # Run individual retargeters
        left_inputs = {"hand_left": inputs["hand_left"]}
        right_inputs = {"hand_right": inputs["hand_right"]}

        self._left_retargeter.compute(left_inputs, left_outputs)
        self._right_retargeter.compute(right_inputs, right_outputs)

        # Combine outputs
        combined_output = outputs["hand_joints"]

        # Map left hand joints
        for src_idx, dst_idx in zip(self._left_indices, self._output_indices_left):
            combined_output[dst_idx] = float(left_outputs["hand_joints"][src_idx])

        # Map right hand joints
        for src_idx, dst_idx in zip(self._right_indices, self._output_indices_right):
            combined_output[dst_idx] = float(right_outputs["hand_joints"][src_idx])

