# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Noitom full-body to G1 upper-body SE3 retargeting for locomanipulation teleop.

Uses **posture-based** arm retargeting: mocap bone *directions* with G1 link
lengths (not scaled human joint positions). Wrist SE(3) targets feed Pink IK.
"""

from __future__ import annotations

import json as _json
import os as _os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    ParameterState,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    RetargeterIO,
)
from isaacteleop.retargeting_engine.interface.tunable_parameter import FloatParameter
from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType
from isaacteleop.retargeting_engine.tensor_types import DLDataType, NDArrayType
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    DeviceIOFullBodyPoseTracked,
)
from isaacteleop.schema import BodyJoint


# PNS/Noitom Y-up -> Isaac Z-up. PNS forward is -Z; axis remap maps it to Isaac -Y.
# Retarget / debug draw then apply operator_faces_robot (+180 deg Z) to align with G1 (+Y).
_NOITOM_TO_ISAAC = np.array(
    [[-1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]],
    dtype=np.float64,
)
_COORD_ROT = Rotation.from_matrix(_NOITOM_TO_ISAAC)

_DEFAULT_LEFT_WRIST_POS = np.array([-0.18, 0.1, 0.8], dtype=np.float64)
_DEFAULT_RIGHT_WRIST_POS = np.array([0.18, 0.1, 0.8], dtype=np.float64)
# G1 locomanipulation VR teleop wrist orientations (see locomanipulation_g1_env_cfg).
_DEFAULT_LEFT_WRIST_QUAT = np.array([-0.2706, 0.6533, 0.2706, 0.6533], dtype=np.float64)
_DEFAULT_RIGHT_WRIST_QUAT = np.array([-0.7071, 0.0, 0.7071, 0.0], dtype=np.float64)
_DEFAULT_ROBOT_PELVIS = np.array([0.0, 0.0, 0.72], dtype=np.float64)
_DEFAULT_ROBOT_PELVIS_QUAT = np.array(
    [0.0, 0.0, np.sqrt(0.5), np.sqrt(0.5)], dtype=np.float64
)
# Approximate G1 shoulder origins in pelvis frame (Isaac Z-up, +Y left).
_ROBOT_LEFT_SHOULDER_OFFSET = np.array([0.05, 0.19, 0.30], dtype=np.float64)
_ROBOT_RIGHT_SHOULDER_OFFSET = np.array([0.05, -0.19, 0.30], dtype=np.float64)
# Torso segment lengths for posture-based reference skeleton (meters, pelvis frame).
_ROBOT_TORSO_SEGMENT_Z = 0.07
_ROBOT_NECK_SEGMENT = 0.08
_ROBOT_HEAD_SEGMENT = 0.12
_ROBOT_HAND_EXTENSION = 0.05
_DELTA_LIMIT = np.array([0.65, 0.65, 0.65], dtype=np.float64)
_WRIST_ORIENTATION_MODES = frozenset({"source", "forearm", "twist", "full"})
DEFAULT_NOITOM_IK_CONFIG_PATH = (
    Path(__file__).resolve().parent / "ik_config" / "noitom_to_g1.json"
)


@dataclass(frozen=True)
class NoitomIkMatch:
    """One declarative human-joint to G1-link IK target mapping."""

    robot_link: str
    human_joint: str
    position_weight: float
    rotation_weight: float
    position_offset: np.ndarray
    rotation_offset_xyzw: np.ndarray


@dataclass(frozen=True)
class NoitomPinkTaskWeights:
    """Pink task weights that are not part of an arm-link mapping."""

    torso_position: float
    torso_rotation: float
    null_space_posture: float


@dataclass(frozen=True)
class NoitomIkConfig:
    """Validated upper-body subset of the GMR-style Noitom mapping config."""

    human_root_name: str
    robot_root_name: str
    arm_chains: dict[str, dict[str, str]]
    human_scale_table: dict[str, float]
    arm_segment_clamps_m: dict[str, float]
    ik_match_table: dict[str, NoitomIkMatch]
    pink_task_weights: NoitomPinkTaskWeights

    def match(self, side: str, role: str) -> NoitomIkMatch:
        return self.ik_match_table[self.arm_chains[side][role]]


@dataclass(frozen=True)
class _ArmBoneScales:
    """Per-arm robot link lengths derived from calibration and config ratios."""

    upper_arm: float  # robot upper-arm length in metres
    forearm: float  # robot forearm length in metres


def load_noitom_ik_config(path: str | _os.PathLike) -> NoitomIkConfig:
    """Load and validate a declarative Noitom-to-G1 upper-body mapping."""
    config_path = Path(path)
    with config_path.open(encoding="utf-8") as config_file:
        raw = _json.load(config_file)

    def require_mapping(key: str) -> dict[str, Any]:
        value = raw.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"{config_path}: {key!r} must be an object")
        return value

    human_root_name = raw.get("human_root_name")
    robot_root_name = raw.get("robot_root_name")
    if not isinstance(human_root_name, str) or not human_root_name:
        raise ValueError(f"{config_path}: 'human_root_name' must be a non-empty string")
    if not isinstance(robot_root_name, str) or not robot_root_name:
        raise ValueError(f"{config_path}: 'robot_root_name' must be a non-empty string")

    raw_pink_task_weights = require_mapping("pink_task_weights")
    pink_task_weight_keys = {
        "torso_position",
        "torso_rotation",
        "null_space_posture",
    }
    if set(raw_pink_task_weights) != pink_task_weight_keys:
        raise ValueError(
            f"{config_path}: pink_task_weights must contain exactly "
            f"{sorted(pink_task_weight_keys)}"
        )
    parsed_pink_task_weights = {
        key: float(raw_pink_task_weights[key]) for key in pink_task_weight_keys
    }
    if any(
        not np.isfinite(value) or value < 0.0
        for value in parsed_pink_task_weights.values()
    ):
        raise ValueError(
            f"{config_path}: Pink task weights must be finite and nonnegative"
        )
    pink_task_weights = NoitomPinkTaskWeights(**parsed_pink_task_weights)

    raw_chains = require_mapping("arm_chains")
    arm_chains: dict[str, dict[str, str]] = {}
    required_roles = {"shoulder", "elbow", "wrist"}
    for side in ("left", "right"):
        raw_chain = raw_chains.get(side)
        if not isinstance(raw_chain, dict) or set(raw_chain) != required_roles:
            raise ValueError(
                f"{config_path}: arm_chains.{side} must contain exactly "
                f"{sorted(required_roles)}"
            )
        if any(not isinstance(link, str) or not link for link in raw_chain.values()):
            raise ValueError(f"{config_path}: arm_chains.{side} links must be strings")
        arm_chains[side] = dict(raw_chain)

    raw_matches = require_mapping("ik_match_table")
    matches: dict[str, NoitomIkMatch] = {}
    for robot_link, entry in raw_matches.items():
        if not isinstance(entry, list) or len(entry) != 5:
            raise ValueError(
                f"{config_path}: ik_match_table.{robot_link} must be "
                "[human_joint, pos_weight, rot_weight, pos_offset, rot_offset_xyzw]"
            )
        human_joint, position_weight, rotation_weight, position_offset, rot_offset = (
            entry
        )
        if not isinstance(human_joint, str) or not hasattr(BodyJoint, human_joint):
            raise ValueError(
                f"{config_path}: unknown BodyJoint joint {human_joint!r} "
                f"for {robot_link}"
            )
        position_offset_array = np.asarray(position_offset, dtype=np.float64)
        rotation_offset_array = np.asarray(rot_offset, dtype=np.float64)
        if position_offset_array.shape != (3,):
            raise ValueError(
                f"{config_path}: {robot_link} position offset must have 3 values"
            )
        if rotation_offset_array.shape != (4,):
            raise ValueError(
                f"{config_path}: {robot_link} rotation offset must have 4 values"
            )
        if not np.all(np.isfinite(position_offset_array)) or not np.all(
            np.isfinite(rotation_offset_array)
        ):
            raise ValueError(f"{config_path}: {robot_link} offsets must be finite")
        if float(np.linalg.norm(rotation_offset_array)) < 1.0e-8:
            raise ValueError(
                f"{config_path}: {robot_link} rotation offset must be nonzero"
            )
        position_weight = float(position_weight)
        rotation_weight = float(rotation_weight)
        if position_weight < 0.0 or rotation_weight < 0.0:
            raise ValueError(f"{config_path}: {robot_link} weights must be nonnegative")
        matches[robot_link] = NoitomIkMatch(
            robot_link=robot_link,
            human_joint=human_joint,
            position_weight=position_weight,
            rotation_weight=rotation_weight,
            position_offset=position_offset_array,
            rotation_offset_xyzw=_normalize_quat(rotation_offset_array),
        )

    referenced_links = {
        link for chain in arm_chains.values() for link in chain.values()
    }
    if set(matches) != referenced_links:
        missing = sorted(referenced_links - set(matches))
        extra = sorted(set(matches) - referenced_links)
        raise ValueError(
            f"{config_path}: ik_match_table must match arm_chains; "
            f"missing={missing}, extra={extra}"
        )

    raw_scales = require_mapping("human_scale_table")
    human_scale_table = {key: float(value) for key, value in raw_scales.items()}
    segment_joint_names = {
        arm_chains[side][role]: matches[arm_chains[side][role]].human_joint
        for side in ("left", "right")
        for role in ("elbow", "wrist")
    }
    missing_scales = sorted(
        joint_name
        for joint_name in segment_joint_names.values()
        if joint_name not in human_scale_table
    )
    if missing_scales:
        raise ValueError(
            f"{config_path}: human_scale_table is missing {missing_scales}"
        )
    if any(
        not np.isfinite(value) or value <= 0.0 for value in human_scale_table.values()
    ):
        raise ValueError(
            f"{config_path}: human scale values must be finite and positive"
        )

    raw_clamps = require_mapping("arm_segment_clamps_m")
    clamp_keys = {
        "upper_arm_min",
        "upper_arm_max",
        "forearm_min",
        "forearm_max",
    }
    if set(raw_clamps) != clamp_keys:
        raise ValueError(
            f"{config_path}: arm_segment_clamps_m must contain exactly {sorted(clamp_keys)}"
        )
    clamps = {key: float(value) for key, value in raw_clamps.items()}
    if (
        clamps["upper_arm_min"] <= 0.0
        or clamps["forearm_min"] <= 0.0
        or clamps["upper_arm_min"] >= clamps["upper_arm_max"]
        or clamps["forearm_min"] >= clamps["forearm_max"]
    ):
        raise ValueError(f"{config_path}: arm segment clamp ranges are invalid")

    return NoitomIkConfig(
        human_root_name=human_root_name,
        robot_root_name=robot_root_name,
        arm_chains=arm_chains,
        human_scale_table=human_scale_table,
        arm_segment_clamps_m=clamps,
        ik_match_table=matches,
        pink_task_weights=pink_task_weights,
    )


def _arm_bone_scales_from_config(
    arm: _ArmCalibration,
    config: NoitomIkConfig,
    side: str,
) -> _ArmBoneScales:
    """Scale measured arm segments and clamp them to configured robot limits."""
    elbow_joint = config.match(side, "elbow").human_joint
    wrist_joint = config.match(side, "wrist").human_joint
    upper_ratio = config.human_scale_table[elbow_joint]
    forearm_ratio = config.human_scale_table[wrist_joint]
    clamps = config.arm_segment_clamps_m

    raw_upper = arm.upper_arm_length * upper_ratio
    raw_forearm = arm.forearm_length * forearm_ratio

    return _ArmBoneScales(
        upper_arm=float(
            np.clip(raw_upper, clamps["upper_arm_min"], clamps["upper_arm_max"])
        ),
        forearm=float(
            np.clip(raw_forearm, clamps["forearm_min"], clamps["forearm_max"])
        ),
    )


@dataclass
class NoitomRetargetingSettings:
    """Tunable retargeting parameters for Noitom-driven G1 upper body."""

    # Fraction of mocap pose applied relative to calibrated neutral (not link length).
    motion_scale: float = 0.55
    # Reduce motion when the solved arm chain is nearly straight (elbow singularity).
    arm_extension_soft_limit: float = 0.72
    # Minimum interior elbow angle (rad) when reconstructing the forearm direction.
    min_elbow_interior_angle: float = 0.65
    # Scale motion when the operator arm span exceeds the G1 link lengths.
    human_reach_margin: float = 0.96
    # Cap how much operator torso twist rotates arm targets (radians).
    max_torso_yaw_delta: float = 0.22
    # Fraction of torso yaw applied to arms (lower = arms ignore body twist).
    torso_yaw_arm_influence: float = 0.35
    # Scale calibration-relative torso yaw/roll/pitch sent to the G1 waist.
    torso_orientation_scale: float = 1.0
    # Torso orientation smoothing alpha (0=hold last, 1=instant).
    torso_rotation_smoothing: float = 0.35
    # Bounds keep the torso target inside the G1 waist's useful workspace.
    torso_yaw_limit_deg: float = 120.0
    torso_roll_limit_deg: float = 24.0
    torso_pitch_limit_deg: float = 24.0
    position_smoothing: float = 0.85
    rotation_smoothing: float = 0.75
    robot_upper_arm_length: float = 0.28
    robot_forearm_length: float = 0.26
    arm_scale_min: float = 0.5
    arm_scale_max: float = 1.5
    robot_pelvis_world: np.ndarray = field(
        default_factory=lambda: _DEFAULT_ROBOT_PELVIS.copy()
    )
    robot_pelvis_quat_xyzw: np.ndarray = field(
        default_factory=lambda: _DEFAULT_ROBOT_PELVIS_QUAT.copy()
    )
    robot_left_shoulder_offset: np.ndarray = field(
        default_factory=lambda: _ROBOT_LEFT_SHOULDER_OFFSET.copy()
    )
    robot_right_shoulder_offset: np.ndarray = field(
        default_factory=lambda: _ROBOT_RIGHT_SHOULDER_OFFSET.copy()
    )
    nominal_left_wrist_pos: np.ndarray = field(
        default_factory=lambda: _DEFAULT_LEFT_WRIST_POS.copy()
    )
    nominal_right_wrist_pos: np.ndarray = field(
        default_factory=lambda: _DEFAULT_RIGHT_WRIST_POS.copy()
    )
    nominal_left_wrist_quat_xyzw: np.ndarray = field(
        default_factory=lambda: _DEFAULT_LEFT_WRIST_QUAT.copy()
    )
    nominal_right_wrist_quat_xyzw: np.ndarray = field(
        default_factory=lambda: _DEFAULT_RIGHT_WRIST_QUAT.copy()
    )
    # "source" directly tracks the robot-aligned BVH wrist axes. "forearm"
    # parallel-transports the calibrated pose, "twist" also adds residual source
    # roll, and "full" retains the calibration-relative 3-axis mapping.
    wrist_orientation_mode: str = "source"
    # Clamp the calibrated Noitom forearm-axis twist before it reaches Pink IK.
    wrist_twist_limit_deg: float = 60.0
    # Limit each retarget update while changing between equivalent twist branches.
    wrist_twist_max_step_deg: float = 4.0
    # Operator stands facing the robot (mirror L/R in horizontal plane).
    operator_faces_robot: bool = True
    # Drive Pink IK wrists to the cyan skeleton wrist joints (shared placement frame).
    track_aligned_mocap_wrists: bool = True
    # Rebuild cyan skeleton with G1 link lengths (bone directions, not human joint spacing).
    reference_use_robot_link_lengths: bool = True
    # Global multiplier on G1 segment lengths for the shared reference skeleton.
    reference_length_scale: float = 1.0
    # Additional scale applied only to upper-arm/forearm segments in reference skeleton.
    reference_arm_length_scale: float = 0.7
    # Scale left-right shoulder span in the reference skeleton (lower = narrower shoulders).
    reference_shoulder_span_scale: float = 0.82
    # Retain mocap pose via bone directions + robot link lengths (not joint positions).
    use_posture_based_arms: bool = True
    # Blend G1 nominal wrist quat with forearm-aligned frame (helps Pink IK converge).
    wrist_orientation_forearm_blend: float = 0.35
    # Feed posture-based elbow positions into Pink IK (narrows shoulder/elbow null space).
    track_elbow_ik_targets: bool = True
    # Feed posture-based shoulder positions into Pink IK (locks shoulder placement).
    track_shoulder_ik_targets: bool = True
    delta_limit: np.ndarray = field(default_factory=lambda: _DELTA_LIMIT.copy())
    sync_nominal_at_calibration: bool = True
    # Without a config, FK uses the fixed arm lengths above.
    ik_config_path: str | None = None


@dataclass
class SE3Pose:
    """Pose in Isaac Z-up world frame (position meters, quaternion xyzw)."""

    position: np.ndarray
    quaternion_xyzw: np.ndarray

    def as_action_pose(self) -> np.ndarray:
        return np.concatenate(
            [
                self.position.astype(np.float32),
                self.quaternion_xyzw.astype(np.float32),
            ]
        )

    @staticmethod
    def from_nominal(position: np.ndarray, quaternion_xyzw: np.ndarray) -> SE3Pose:
        return SE3Pose(position.copy(), quaternion_xyzw.copy())


@dataclass
class ArmIkTargets:
    """Pink IK frame targets for one upper-body update."""

    left_wrist: SE3Pose
    right_wrist: SE3Pose
    torso: SE3Pose
    left_elbow: SE3Pose
    right_elbow: SE3Pose
    left_shoulder: SE3Pose
    right_shoulder: SE3Pose


@dataclass(frozen=True)
class _DeclarativeArmTargets:
    """Shoulder, elbow, and wrist targets produced by one config-driven solve."""

    shoulder: SE3Pose
    elbow: SE3Pose
    wrist: SE3Pose


@dataclass
class NoitomCalibrationView:
    """Read-only calibration snapshot for debug visualization alignment."""

    pelvis_world: np.ndarray
    body_yaw_isaac: float
    arm_length_scale: float
    body_height_scale: float


@dataclass(frozen=True)
class WristOrientationDiagnostics:
    """One wrist's source and target rotations for low-rate diagnostics."""

    world_quaternion_xyzw: np.ndarray
    reference_quaternion_xyzw: np.ndarray
    torso_quaternion_xyzw: np.ndarray
    world_delta_rotvec_deg: np.ndarray
    torso_delta_rotvec_deg: np.ndarray
    forearm_swing_deg: float
    twist_deg: float
    bounded_twist_deg: float
    target_quaternion_xyzw: np.ndarray
    source_target_error_deg: float
    aligned_raw_quaternion_xyzw: np.ndarray
    semantic_quaternion_xyzw: np.ndarray
    local_offset_xyzw: np.ndarray
    raw_x_dot_forearm: float | None
    semantic_x_dot_forearm: float | None
    semantic_x_world: np.ndarray
    semantic_y_world: np.ndarray
    semantic_z_world: np.ndarray


@dataclass(frozen=True)
class WristPoseDiagnostics:
    """Raw, robot-aligned raw, and anatomy-normalized BVH wrist poses."""

    bvh_raw_isaac_world: SE3Pose
    bvh_aligned_raw_world: SE3Pose
    bvh_semantic_world: SE3Pose
    local_offset_xyzw: np.ndarray
    raw_x_dot_forearm: float | None
    semantic_x_dot_forearm: float | None
    semantic_x_world: np.ndarray
    semantic_y_world: np.ndarray
    semantic_z_world: np.ndarray


@dataclass
class _TorsoFrame:
    origin: np.ndarray
    rotation: Rotation


@dataclass
class _ArmCalibration:
    shoulder_torso: np.ndarray
    shoulder_world: np.ndarray
    elbow_world: np.ndarray
    wrist_pos_torso: np.ndarray
    wrist_rot_torso: Rotation
    wrist_rel_pelvis: np.ndarray
    wrist_world: np.ndarray
    upper_arm_length: float
    forearm_length: float


@dataclass
class _CalibrationState:
    torso: _TorsoFrame
    left: _ArmCalibration
    right: _ArmCalibration
    arm_length_scale: float
    body_height_scale: float
    body_yaw_isaac: float
    pelvis_world: np.ndarray
    nominal_left: SE3Pose
    nominal_right: SE3Pose
    neutral_left_forearm_robot: np.ndarray
    neutral_right_forearm_robot: np.ndarray
    nominal_left_elbow: SE3Pose
    nominal_right_elbow: SE3Pose
    nominal_left_shoulder: SE3Pose
    nominal_right_shoulder: SE3Pose
    left_arm_bone_scales: _ArmBoneScales | None = None
    right_arm_bone_scales: _ArmBoneScales | None = None


class NoitomArmIkTargetNode:
    """Own smoothed IK targets and bounded wrist-twist state for one arm."""

    def __init__(
        self,
        is_left: bool,
        settings: NoitomRetargetingSettings,
        nominal_wrist_pos: np.ndarray,
        nominal_wrist_quat_xyzw: np.ndarray,
    ) -> None:
        self._is_left = is_left
        # Shared reference — parameter updates propagate without extra wiring.
        self._settings = settings
        self._nominal_pos = np.asarray(nominal_wrist_pos, dtype=np.float64).copy()
        self._nominal_quat = np.asarray(
            nominal_wrist_quat_xyzw, dtype=np.float64
        ).copy()

        self._smoothed_wrist = SE3Pose.from_nominal(
            self._nominal_pos, self._nominal_quat
        )
        self._smoothed_elbow = self._build_default_elbow()
        self._smoothed_shoulder = self._build_default_shoulder()
        # Bounded wrist twist — None until calibration + first retarget frame.
        self._bounded_twist_rad: float | None = None

    # ------------------------------------------------------------------
    # Read-only pose accessors
    # ------------------------------------------------------------------

    @property
    def current_wrist(self) -> SE3Pose:
        return self._smoothed_wrist

    @property
    def current_elbow(self) -> SE3Pose:
        return self._smoothed_elbow

    @property
    def current_shoulder(self) -> SE3Pose:
        return self._smoothed_shoulder

    @property
    def bounded_twist_rad(self) -> float | None:
        return self._bounded_twist_rad

    # ------------------------------------------------------------------
    # State reset helpers
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Restore factory-default poses (on clear_calibration / episode reset)."""
        self._smoothed_wrist = SE3Pose.from_nominal(
            self._nominal_pos, self._nominal_quat
        )
        self._smoothed_elbow = self._build_default_elbow()
        self._smoothed_shoulder = self._build_default_shoulder()
        self._bounded_twist_rad = None

    def reset_to_nominal(
        self,
        nominal_wrist: SE3Pose,
        nominal_elbow: SE3Pose,
        nominal_shoulder: SE3Pose,
    ) -> None:
        """Sync smoothed poses to calibration-time nominal poses and clear twist.

        Called by ``NoitomG1Retargeter.calibrate()`` after a successful
        ``_CalibrationState`` is built so the arm starts from neutral on the
        first live retarget frame.
        """
        self._smoothed_wrist = nominal_wrist
        self._smoothed_elbow = nominal_elbow
        self._smoothed_shoulder = nominal_shoulder
        self._bounded_twist_rad = None

    def reset_bounded_twist(self) -> None:
        """Reset twist accumulator (called when calibration is cleared mid-episode)."""
        self._bounded_twist_rad = None

    # ------------------------------------------------------------------
    # Bounded wrist-twist accumulator
    # ------------------------------------------------------------------

    def apply_bound_twist(self, raw_twist_rad: float) -> float:
        """Choose the nearest equivalent twist angle, clamp, then slew-rate-limit.

        Mirrors the logic that was in ``NoitomG1Retargeter._bound_wrist_twist``.
        The accumulator enables continuous crossing of ±π without accumulating
        full turns that the G1 wrist cannot represent.
        """
        previous = self._bounded_twist_rad
        nearest = _unwrap_angle_near(raw_twist_rad, previous)
        desired = _clamp_wrist_twist(nearest, self._settings.wrist_twist_limit_deg)
        # Never retain unbounded 2*pi winding for a bounded robot joint. Noitom's
        # residual can loop during fast arm motion; keeping that winding made the
        # old state stick at one wrist limit long after the source returned.
        if previous is not None and self._settings.wrist_twist_max_step_deg > 0.0:
            max_step_rad = float(np.deg2rad(self._settings.wrist_twist_max_step_deg))
            desired = previous + float(
                np.clip(desired - previous, -max_step_rad, max_step_rad)
            )
        bounded = _clamp_wrist_twist(desired, self._settings.wrist_twist_limit_deg)
        self._bounded_twist_rad = bounded
        return bounded

    # ------------------------------------------------------------------
    # Smoothing update helpers
    # ------------------------------------------------------------------

    def update_wrist(self, target: SE3Pose) -> SE3Pose:
        """Exponentially smooth wrist pose toward *target*; return result."""
        self._smoothed_wrist = _smooth_pose(
            self._smoothed_wrist,
            target,
            self._settings.position_smoothing,
            self._settings.rotation_smoothing,
        )
        return self._smoothed_wrist

    def update_elbow(self, target: SE3Pose) -> SE3Pose:
        """Exponentially smooth elbow pose toward *target*; return result."""
        self._smoothed_elbow = _smooth_pose(
            self._smoothed_elbow,
            target,
            self._settings.position_smoothing,
            self._settings.rotation_smoothing,
        )
        return self._smoothed_elbow

    def update_shoulder(self, target: SE3Pose) -> SE3Pose:
        """Exponentially smooth shoulder pose toward *target*; return result."""
        self._smoothed_shoulder = _smooth_pose(
            self._smoothed_shoulder,
            target,
            self._settings.position_smoothing,
            self._settings.rotation_smoothing,
        )
        return self._smoothed_shoulder

    # ------------------------------------------------------------------
    # Default pose builders
    # ------------------------------------------------------------------

    def _build_default_elbow(self) -> SE3Pose:
        """Elbow directly below G1 shoulder — arms-down rest posture."""
        shoulder = _shoulder_world_robot(self._settings, 0.0, self._is_left)
        upper_dir = np.array([0.0, 0.0, -1.0], dtype=np.float64)
        elbow = shoulder + upper_dir * self._settings.robot_upper_arm_length
        quat = _elbow_quat_for_ik(upper_dir, self._nominal_quat, self._settings)
        return SE3Pose(elbow, quat)

    def _build_default_shoulder(self) -> SE3Pose:
        """Shoulder at G1 shoulder origin — arms-down rest posture."""
        shoulder = _shoulder_world_robot(self._settings, 0.0, self._is_left)
        upper_dir = np.array([0.0, 0.0, -1.0], dtype=np.float64)
        quat = _elbow_quat_for_ik(upper_dir, self._nominal_quat, self._settings)
        return SE3Pose(shoulder, quat)


class NoitomG1Retargeter(BaseRetargeter):
    """Retarget Noitom upper-body motion to G1 arm SE3 targets for Pink IK."""

    def __init__(
        self,
        settings: NoitomRetargetingSettings | None = None,
        name: str = "noitom_g1_retargeter",
    ) -> None:
        self._settings = settings or NoitomRetargetingSettings()
        if self._settings.wrist_orientation_mode not in _WRIST_ORIENTATION_MODES:
            raise ValueError(
                "wrist_orientation_mode must be one of "
                f"{sorted(_WRIST_ORIENTATION_MODES)}, got "
                f"{self._settings.wrist_orientation_mode!r}"
            )
        if self._settings.torso_orientation_scale < 0.0:
            raise ValueError("torso_orientation_scale must be nonnegative")
        torso_limits = (
            self._settings.torso_yaw_limit_deg,
            self._settings.torso_roll_limit_deg,
            self._settings.torso_pitch_limit_deg,
        )
        if any(limit <= 0.0 for limit in torso_limits):
            raise ValueError("torso orientation limits must be positive")
        self._nominal_left = SE3Pose.from_nominal(
            self._settings.nominal_left_wrist_pos,
            self._settings.nominal_left_wrist_quat_xyzw,
        )
        self._nominal_right = SE3Pose.from_nominal(
            self._settings.nominal_right_wrist_pos,
            self._settings.nominal_right_wrist_quat_xyzw,
        )
        self._calibration: _CalibrationState | None = None
        self._latest_torso: _TorsoFrame | None = None
        self._current_torso = self._neutral_torso_target()
        self._ik_config: NoitomIkConfig | None = None
        if self._settings.ik_config_path is not None:
            self._ik_config = load_noitom_ik_config(self._settings.ik_config_path)
        self._left_arm = NoitomArmIkTargetNode(
            is_left=True,
            settings=self._settings,
            nominal_wrist_pos=self._nominal_left.position,
            nominal_wrist_quat_xyzw=self._nominal_left.quaternion_xyzw,
        )
        self._right_arm = NoitomArmIkTargetNode(
            is_left=False,
            settings=self._settings,
            nominal_wrist_pos=self._nominal_right.position,
            nominal_wrist_quat_xyzw=self._nominal_right.quaternion_xyzw,
        )

        param_state = ParameterState(
            name,
            parameters=[
                FloatParameter(
                    "motion_scale",
                    "Pose amplitude vs calibrated neutral (0=hold, 1=full mocap posture).",
                    default_value=self._settings.motion_scale,
                    min_value=0.0,
                    max_value=1.0,
                    step_size=0.05,
                    sync_fn=lambda v: setattr(self._settings, "motion_scale", v),
                ),
                FloatParameter(
                    "torso_orientation_scale",
                    "Calibration-relative torso orientation amplitude.",
                    default_value=self._settings.torso_orientation_scale,
                    min_value=0.0,
                    max_value=1.5,
                    step_size=0.05,
                    sync_fn=lambda v: setattr(
                        self._settings, "torso_orientation_scale", v
                    ),
                ),
                FloatParameter(
                    "position_smoothing",
                    "Position smoothing alpha (0=hold last, 1=instant).",
                    default_value=self._settings.position_smoothing,
                    min_value=0.0,
                    max_value=1.0,
                    step_size=0.05,
                    sync_fn=lambda v: setattr(self._settings, "position_smoothing", v),
                ),
                FloatParameter(
                    "rotation_smoothing",
                    "Rotation smoothing alpha (0=hold last, 1=instant).",
                    default_value=self._settings.rotation_smoothing,
                    min_value=0.0,
                    max_value=1.0,
                    step_size=0.05,
                    sync_fn=lambda v: setattr(self._settings, "rotation_smoothing", v),
                ),
                FloatParameter(
                    "robot_upper_arm_length",
                    "Robot upper arm length for reach clamping [m].",
                    default_value=self._settings.robot_upper_arm_length,
                    min_value=0.05,
                    max_value=0.5,
                    step_size=0.01,
                    sync_fn=lambda v: setattr(
                        self._settings, "robot_upper_arm_length", v
                    ),
                ),
                FloatParameter(
                    "robot_forearm_length",
                    "Robot forearm length for reach clamping [m].",
                    default_value=self._settings.robot_forearm_length,
                    min_value=0.05,
                    max_value=0.5,
                    step_size=0.01,
                    sync_fn=lambda v: setattr(
                        self._settings, "robot_forearm_length", v
                    ),
                ),
                FloatParameter(
                    "arm_scale_min",
                    "Minimum arm length scale (robot/human ratio floor).",
                    default_value=self._settings.arm_scale_min,
                    min_value=0.1,
                    max_value=1.0,
                    step_size=0.05,
                    sync_fn=lambda v: setattr(self._settings, "arm_scale_min", v),
                ),
                FloatParameter(
                    "arm_scale_max",
                    "Maximum arm length scale (robot/human ratio ceiling).",
                    default_value=self._settings.arm_scale_max,
                    min_value=1.0,
                    max_value=3.0,
                    step_size=0.05,
                    sync_fn=lambda v: setattr(self._settings, "arm_scale_max", v),
                ),
            ],
        )

        super().__init__(name=name, parameter_state=param_state)

    @property
    def is_calibrated(self) -> bool:
        return self._calibration is not None

    @property
    def awaiting_calibration(self) -> bool:
        return self._calibration is None

    @property
    def current_left(self) -> SE3Pose:
        return self._left_arm.current_wrist

    @property
    def current_right(self) -> SE3Pose:
        return self._right_arm.current_wrist

    @property
    def current_torso(self) -> SE3Pose:
        return self._current_torso

    @property
    def current_left_elbow(self) -> SE3Pose:
        return self._left_arm.current_elbow

    @property
    def current_right_elbow(self) -> SE3Pose:
        return self._right_arm.current_elbow

    @property
    def current_left_shoulder(self) -> SE3Pose:
        return self._left_arm.current_shoulder

    @property
    def current_right_shoulder(self) -> SE3Pose:
        return self._right_arm.current_shoulder

    @property
    def current_arm_targets(self) -> ArmIkTargets:
        return ArmIkTargets(
            left_wrist=self._left_arm.current_wrist,
            right_wrist=self._right_arm.current_wrist,
            torso=self._current_torso,
            left_elbow=self._left_arm.current_elbow,
            right_elbow=self._right_arm.current_elbow,
            left_shoulder=self._left_arm.current_shoulder,
            right_shoulder=self._right_arm.current_shoulder,
        )

    @property
    def calibration_view(self) -> NoitomCalibrationView | None:
        if self._calibration is None:
            return None
        calib = self._calibration
        return NoitomCalibrationView(
            pelvis_world=calib.pelvis_world.copy(),
            body_yaw_isaac=calib.body_yaw_isaac,
            arm_length_scale=calib.arm_length_scale,
            body_height_scale=calib.body_height_scale,
        )

    @property
    def body_yaw_isaac(self) -> float:
        if self._latest_torso is None:
            return 0.0
        return _compute_torso_yaw(self._latest_torso)

    @property
    def body_yaw_delta(self) -> float:
        if self._calibration is None:
            return 0.0
        return self.body_yaw_isaac - self._calibration.body_yaw_isaac

    @property
    def retargeting_settings(self) -> NoitomRetargetingSettings:
        return self._settings

    @property
    def ik_config(self) -> NoitomIkConfig | None:
        """Return the validated declarative mapping, when config mode is enabled."""
        return self._ik_config

    def _wrist_local_offset(self, side: str) -> np.ndarray:
        if self._ik_config is None:
            return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
        return self._ik_config.match(side, "wrist").rotation_offset_xyzw.copy()

    @property
    def calibration_bone_scales(
        self,
    ) -> tuple[_ArmBoneScales, _ArmBoneScales] | None:
        """Return calibrated left/right robot arm link lengths when available."""
        if self._calibration is None:
            return None
        left = self._calibration.left_arm_bone_scales
        right = self._calibration.right_arm_bone_scales
        if left is None or right is None:
            return None
        return left, right

    @property
    def neutral_arms(self) -> tuple[_ArmCalibration, _ArmCalibration] | None:
        if self._calibration is None:
            return None
        return self._calibration.left, self._calibration.right

    def wrist_orientation_diagnostics(
        self, frame: Any
    ) -> dict[str, WristOrientationDiagnostics] | None:
        """Return rotations needed to distinguish world/torso mapping from IK error."""
        if self._calibration is None:
            return None
        parsed = _parse_upper_body(frame)
        if parsed is None:
            return None
        torso, left, right, _pelvis_world = parsed
        calib = self._calibration
        aligned_positions = self.reference_skeleton_positions(frame)

        def target_forearm_direction(side: str) -> np.ndarray | None:
            elbow_index = int(
                BodyJoint.LEFT_ELBOW if side == "left" else BodyJoint.RIGHT_ELBOW
            )
            wrist_index = int(
                BodyJoint.LEFT_WRIST if side == "left" else BodyJoint.RIGHT_WRIST
            )
            elbow_position = aligned_positions.get(elbow_index)
            wrist_position = aligned_positions.get(wrist_index)
            if elbow_position is None or wrist_position is None:
                return None
            forearm = wrist_position - elbow_position
            norm = float(np.linalg.norm(forearm))
            return None if norm < 1.0e-8 else forearm / norm

        def make_diagnostics(
            side: str,
            arm: _ArmCalibration,
            neutral: _ArmCalibration,
            target: SE3Pose,
        ) -> WristOrientationDiagnostics:
            wrist_world = torso.rotation * arm.wrist_rot_torso
            aligned_raw = _aligned_source_wrist_rotation(torso, arm)
            local_offset = self._wrist_local_offset(side)
            semantic = _semantic_source_wrist_rotation(aligned_raw, local_offset)
            reference = (
                semantic
                if self._settings.wrist_orientation_mode == "source"
                else aligned_raw
            )
            forearm_direction = target_forearm_direction(side)
            raw_x = aligned_raw.as_matrix()[:, 0]
            semantic_basis = semantic.as_matrix()
            neutral_world = calib.torso.rotation * neutral.wrist_rot_torso
            world_delta = wrist_world * neutral_world.inv()
            torso_delta = arm.wrist_rot_torso * neutral.wrist_rot_torso.inv()
            forearm_swing = _source_forearm_swing_rotation(
                arm,
                neutral,
                calib.torso,
            )
            twist_rad = _wrist_twist_delta_rad(
                torso,
                arm,
                calib.torso,
                neutral,
            )
            arm_node = self._left_arm if side == "left" else self._right_arm
            bounded_twist_rad = arm_node.bounded_twist_rad
            if bounded_twist_rad is None:
                bounded_twist_rad = _clamp_wrist_twist(
                    twist_rad, self._settings.wrist_twist_limit_deg
                )
            return WristOrientationDiagnostics(
                world_quaternion_xyzw=_normalize_quat(wrist_world.as_quat()),
                reference_quaternion_xyzw=_normalize_quat(reference.as_quat()),
                torso_quaternion_xyzw=_normalize_quat(arm.wrist_rot_torso.as_quat()),
                world_delta_rotvec_deg=np.rad2deg(world_delta.as_rotvec()),
                torso_delta_rotvec_deg=np.rad2deg(torso_delta.as_rotvec()),
                forearm_swing_deg=float(np.rad2deg(forearm_swing.magnitude())),
                twist_deg=float(np.rad2deg(twist_rad)),
                bounded_twist_deg=float(np.rad2deg(bounded_twist_rad)),
                target_quaternion_xyzw=target.quaternion_xyzw.copy(),
                source_target_error_deg=float(
                    np.rad2deg(
                        (
                            reference.inv() * Rotation.from_quat(target.quaternion_xyzw)
                        ).magnitude()
                    )
                ),
                aligned_raw_quaternion_xyzw=_normalize_quat(aligned_raw.as_quat()),
                semantic_quaternion_xyzw=_normalize_quat(semantic.as_quat()),
                local_offset_xyzw=local_offset,
                raw_x_dot_forearm=(
                    None
                    if forearm_direction is None
                    else float(np.dot(raw_x, forearm_direction))
                ),
                semantic_x_dot_forearm=(
                    None
                    if forearm_direction is None
                    else float(np.dot(semantic_basis[:, 0], forearm_direction))
                ),
                semantic_x_world=semantic_basis[:, 0].copy(),
                semantic_y_world=semantic_basis[:, 1].copy(),
                semantic_z_world=semantic_basis[:, 2].copy(),
            )

        return {
            "left": make_diagnostics(
                "left", left, calib.left, self._left_arm.current_wrist
            ),
            "right": make_diagnostics(
                "right", right, calib.right, self._right_arm.current_wrist
            ),
        }

    def wrist_pose_diagnostics(
        self, frame: Any
    ) -> dict[str, WristPoseDiagnostics] | None:
        """Return raw and semantic-normalized wrist poses for layered diagnostics."""
        raw_poses = {
            "left": _joint_pose(frame, BodyJoint.LEFT_WRIST),
            "right": _joint_pose(frame, BodyJoint.RIGHT_WRIST),
        }
        if any(pose is None for pose in raw_poses.values()):
            return None

        parsed = _parse_upper_body(frame)
        if parsed is None:
            return None
        torso, left_arm, right_arm, _pelvis_world = parsed
        aligned_positions = self.reference_skeleton_positions(frame)
        joint_indices = {
            "left": int(BodyJoint.LEFT_WRIST),
            "right": int(BodyJoint.RIGHT_WRIST),
        }
        required_indices = {
            *joint_indices.values(),
            int(BodyJoint.LEFT_ELBOW),
            int(BodyJoint.RIGHT_ELBOW),
        }
        if any(index not in aligned_positions for index in required_indices):
            return None

        diagnostics: dict[str, WristPoseDiagnostics] = {}
        for side, arm, elbow_index in (
            ("left", left_arm, int(BodyJoint.LEFT_ELBOW)),
            ("right", right_arm, int(BodyJoint.RIGHT_ELBOW)),
        ):
            joint_index = joint_indices[side]
            raw_pose = raw_poses[side]
            assert raw_pose is not None
            aligned_raw = _aligned_source_wrist_rotation(torso, arm)
            local_offset = self._wrist_local_offset(side)
            semantic = _semantic_source_wrist_rotation(aligned_raw, local_offset)
            forearm = aligned_positions[joint_index] - aligned_positions[elbow_index]
            forearm_norm = float(np.linalg.norm(forearm))
            forearm_direction = (
                None if forearm_norm < 1.0e-8 else forearm / forearm_norm
            )
            raw_basis = aligned_raw.as_matrix()
            semantic_basis = semantic.as_matrix()
            diagnostics[side] = WristPoseDiagnostics(
                bvh_raw_isaac_world=SE3Pose(
                    raw_pose.position.copy(), raw_pose.quaternion_xyzw.copy()
                ),
                bvh_aligned_raw_world=SE3Pose(
                    aligned_positions[joint_index].copy(),
                    _normalize_quat(aligned_raw.as_quat()),
                ),
                bvh_semantic_world=SE3Pose(
                    aligned_positions[joint_index].copy(),
                    _normalize_quat(semantic.as_quat()),
                ),
                local_offset_xyzw=local_offset,
                raw_x_dot_forearm=(
                    None
                    if forearm_direction is None
                    else float(np.dot(raw_basis[:, 0], forearm_direction))
                ),
                semantic_x_dot_forearm=(
                    None
                    if forearm_direction is None
                    else float(np.dot(semantic_basis[:, 0], forearm_direction))
                ),
                semantic_x_world=semantic_basis[:, 0].copy(),
                semantic_y_world=semantic_basis[:, 1].copy(),
                semantic_z_world=semantic_basis[:, 2].copy(),
            )
        return diagnostics

    def reference_wrist_frames(self, frame: Any) -> dict[str, SE3Pose]:
        """Return BVH wrist axes used for viewport comparison with G1 wrists."""
        parsed = _parse_upper_body(frame)
        if parsed is None:
            return {}
        torso, left, right, _pelvis_world = parsed
        if self._calibration is None:
            calib_view = None
        else:
            calib_view = _calibration_view_from_state(self._calibration)
        positions = _aligned_skeleton_positions(frame, self._settings, calib_view)
        frames: dict[str, SE3Pose] = {}
        for side, arm, joint_index in (
            ("left", left, BodyJoint.LEFT_WRIST),
            ("right", right, BodyJoint.RIGHT_WRIST),
        ):
            position = positions.get(int(joint_index))
            if position is None:
                continue
            aligned_raw = _aligned_source_wrist_rotation(torso, arm)
            orientation = (
                _semantic_source_wrist_rotation(
                    aligned_raw, self._wrist_local_offset(side)
                )
                if self._settings.wrist_orientation_mode == "source"
                else aligned_raw
            )
            frames[side] = SE3Pose(
                position.copy(), _normalize_quat(orientation.as_quat())
            )
        return frames

    def reference_skeleton_positions(self, frame: Any) -> dict[int, np.ndarray]:
        """Return cyan-skeleton positions with config-driven arm targets overlaid."""
        calib_view = (
            None
            if self._calibration is None
            else _calibration_view_from_state(self._calibration)
        )
        positions = _aligned_skeleton_positions(frame, self._settings, calib_view)
        if self._ik_config is None or self._calibration is None:
            return positions

        targets = self.current_arm_targets
        for is_left, shoulder, elbow, wrist in (
            (
                True,
                targets.left_shoulder.position,
                targets.left_elbow.position,
                targets.left_wrist.position,
            ),
            (
                False,
                targets.right_shoulder.position,
                targets.right_elbow.position,
                targets.right_wrist.position,
            ),
        ):
            shoulder_joint = (
                BodyJoint.LEFT_SHOULDER if is_left else BodyJoint.RIGHT_SHOULDER
            )
            elbow_joint = BodyJoint.LEFT_ELBOW if is_left else BodyJoint.RIGHT_ELBOW
            wrist_joint = BodyJoint.LEFT_WRIST if is_left else BodyJoint.RIGHT_WRIST
            hand_joint = BodyJoint.LEFT_HAND if is_left else BodyJoint.RIGHT_HAND
            positions[int(shoulder_joint)] = shoulder.copy()
            positions[int(elbow_joint)] = elbow.copy()
            positions[int(wrist_joint)] = wrist.copy()
            positions[int(hand_joint)] = (
                wrist + _unit_direction(wrist - elbow) * _ROBOT_HAND_EXTENSION
            )

        spine3 = positions.get(int(BodyJoint.SPINE3))
        if spine3 is not None:
            for collar_joint, shoulder_joint in (
                (BodyJoint.LEFT_COLLAR, BodyJoint.LEFT_SHOULDER),
                (BodyJoint.RIGHT_COLLAR, BodyJoint.RIGHT_SHOULDER),
            ):
                shoulder = positions.get(int(shoulder_joint))
                if shoulder is not None:
                    positions[int(collar_joint)] = 0.5 * (spine3 + shoulder)
        return positions

    def clear_calibration(self) -> None:
        self._calibration = None
        self._latest_torso = None
        self._current_torso = self._neutral_torso_target()
        self._left_arm.reset()
        self._right_arm.reset()

    def _neutral_torso_target(self) -> SE3Pose:
        return SE3Pose(
            self._settings.robot_pelvis_world.astype(np.float64).copy(),
            _normalize_quat(self._settings.robot_pelvis_quat_xyzw),
        )

    def calibrate(self, frame: Any) -> bool:
        self._sync_parameters_from_state()
        parsed = _parse_upper_body(frame)
        if parsed is None:
            return False
        torso, left, right, pelvis_world = parsed
        self._latest_torso = torso
        human_arm = (
            left.upper_arm_length
            + left.forearm_length
            + right.upper_arm_length
            + right.forearm_length
        ) * 0.5
        robot_arm = (
            self._settings.robot_upper_arm_length + self._settings.robot_forearm_length
        )
        if human_arm < 1e-4:
            return False
        raw_scale = robot_arm / human_arm
        arm_scale = float(
            np.clip(
                raw_scale, self._settings.arm_scale_min, self._settings.arm_scale_max
            )
        )
        shoulder_world = torso.origin + torso.rotation.apply(left.shoulder_torso)
        shoulder_rel_z = float((shoulder_world - pelvis_world)[2])
        robot_shoulder_z = float(self._settings.robot_left_shoulder_offset[2])
        if shoulder_rel_z > 0.1:
            raw_body_scale = robot_shoulder_z / shoulder_rel_z
        else:
            raw_body_scale = arm_scale
        body_height_scale = float(np.clip(raw_body_scale, 0.45, 1.15))

        # Config mode derives a separate target length for every arm segment. The
        # config-free branch below remains the exact Phase-A numerical path.
        left_bone_scales: _ArmBoneScales | None = None
        right_bone_scales: _ArmBoneScales | None = None
        if self._ik_config is not None:
            left_bone_scales = _arm_bone_scales_from_config(
                left, self._ik_config, "left"
            )
            right_bone_scales = _arm_bone_scales_from_config(
                right, self._ik_config, "right"
            )
            calibration_view = _calibration_view_from_scales(
                arm_scale, body_height_scale, pelvis_world
            )
            aligned_positions = _aligned_skeleton_positions(
                frame, self._settings, calibration_view
            )
            left_shoulder_position = aligned_positions.get(int(BodyJoint.LEFT_SHOULDER))
            right_shoulder_position = aligned_positions.get(
                int(BodyJoint.RIGHT_SHOULDER)
            )
            if left_shoulder_position is None or right_shoulder_position is None:
                return False
            left_targets = _declarative_arm_targets(
                torso=torso,
                arm=left,
                neutral_torso=torso,
                neutral=left,
                settings=self._settings,
                is_left=True,
                bone_scales=left_bone_scales,
                config=self._ik_config,
                bounded_twist_rad=0.0,
                shoulder_position=left_shoulder_position,
            )
            right_targets = _declarative_arm_targets(
                torso=torso,
                arm=right,
                neutral_torso=torso,
                neutral=right,
                settings=self._settings,
                is_left=False,
                bone_scales=right_bone_scales,
                config=self._ik_config,
                bounded_twist_rad=0.0,
                shoulder_position=right_shoulder_position,
            )
            nominal_left = left_targets.wrist
            nominal_right = right_targets.wrist
            nominal_left_elbow = left_targets.elbow
            nominal_right_elbow = right_targets.elbow
            nominal_left_shoulder = left_targets.shoulder
            nominal_right_shoulder = right_targets.shoulder
            neutral_left_forearm_robot = _unit_direction(
                nominal_left.position - nominal_left_elbow.position
            )
            neutral_right_forearm_robot = _unit_direction(
                nominal_right.position - nominal_right_elbow.position
            )
        else:
            if self._settings.sync_nominal_at_calibration:
                if self._settings.track_aligned_mocap_wrists:
                    nominal_left, nominal_right = _nominal_wrists_from_aligned_frame(
                        frame,
                        self._settings,
                        arm_scale,
                        body_height_scale,
                        pelvis_world,
                    )
                    if nominal_left is None or nominal_right is None:
                        return False
                elif self._settings.use_posture_based_arms:
                    nominal_left = _wrist_pose_from_posture(
                        left,
                        self._settings,
                        is_left=True,
                        yaw_delta=0.0,
                        nominal_quat=self._settings.nominal_left_wrist_quat_xyzw,
                    )
                    nominal_right = _wrist_pose_from_posture(
                        right,
                        self._settings,
                        is_left=False,
                        yaw_delta=0.0,
                        nominal_quat=self._settings.nominal_right_wrist_quat_xyzw,
                    )
                else:
                    nominal_left = SE3Pose.from_nominal(
                        self._nominal_left.position,
                        self._nominal_left.quaternion_xyzw,
                    )
                    nominal_right = SE3Pose.from_nominal(
                        self._nominal_right.position,
                        self._nominal_right.quaternion_xyzw,
                    )
            else:
                nominal_left = SE3Pose.from_nominal(
                    self._nominal_left.position, self._nominal_left.quaternion_xyzw
                )
                nominal_right = SE3Pose.from_nominal(
                    self._nominal_right.position, self._nominal_right.quaternion_xyzw
                )

            if self._settings.wrist_orientation_mode == "source":
                # Config-free source mode starts from the aligned BVH frames used by
                # updates and visualization.
                nominal_left.quaternion_xyzw = _normalize_quat(
                    _aligned_source_wrist_rotation(torso, left).as_quat()
                )
                nominal_right.quaternion_xyzw = _normalize_quat(
                    _aligned_source_wrist_rotation(torso, right).as_quat()
                )

            neutral_forearms = _neutral_robot_forearm_directions(
                frame,
                left,
                right,
                self._settings,
                arm_scale,
                body_height_scale,
                pelvis_world,
            )
            if neutral_forearms is None:
                return False
            neutral_left_forearm_robot, neutral_right_forearm_robot = neutral_forearms

            nominal_left_elbow = self._left_arm._build_default_elbow()
            nominal_right_elbow = self._right_arm._build_default_elbow()
            if (
                self._settings.track_elbow_ik_targets
                and self._settings.sync_nominal_at_calibration
            ):
                elbow_pair = _nominal_elbows_from_aligned_frame(
                    frame,
                    self._settings,
                    arm_scale,
                    body_height_scale,
                    pelvis_world,
                )
                if elbow_pair is not None:
                    nominal_left_elbow, nominal_right_elbow = elbow_pair

            nominal_left_shoulder = self._left_arm._build_default_shoulder()
            nominal_right_shoulder = self._right_arm._build_default_shoulder()
            if (
                self._settings.track_shoulder_ik_targets
                and self._settings.sync_nominal_at_calibration
            ):
                shoulder_pair = _nominal_shoulders_from_aligned_frame(
                    frame,
                    self._settings,
                    arm_scale,
                    body_height_scale,
                    pelvis_world,
                )
                if shoulder_pair is not None:
                    nominal_left_shoulder, nominal_right_shoulder = shoulder_pair

        self._calibration = _CalibrationState(
            torso=torso,
            left=left,
            right=right,
            arm_length_scale=arm_scale,
            body_height_scale=body_height_scale,
            body_yaw_isaac=_compute_torso_yaw(torso),
            pelvis_world=pelvis_world,
            nominal_left=nominal_left,
            nominal_right=nominal_right,
            neutral_left_forearm_robot=neutral_left_forearm_robot,
            neutral_right_forearm_robot=neutral_right_forearm_robot,
            nominal_left_elbow=nominal_left_elbow,
            nominal_right_elbow=nominal_right_elbow,
            nominal_left_shoulder=nominal_left_shoulder,
            nominal_right_shoulder=nominal_right_shoulder,
            left_arm_bone_scales=left_bone_scales,
            right_arm_bone_scales=right_bone_scales,
        )
        self._left_arm.reset_to_nominal(
            nominal_left, nominal_left_elbow, nominal_left_shoulder
        )
        self._right_arm.reset_to_nominal(
            nominal_right, nominal_right_elbow, nominal_right_shoulder
        )
        self._current_torso = self._neutral_torso_target()
        return True

    def retarget(self, frame: Any) -> ArmIkTargets | None:
        self._sync_parameters_from_state()
        if self._calibration is None:
            return None
        parsed = _parse_upper_body(frame)
        if parsed is None:
            return None

        torso, left, right, pelvis_world = parsed
        self._latest_torso = torso
        calib = self._calibration
        torso_target = _torso_target_from_relative_motion(
            torso, calib.torso, self._settings
        )
        self._current_torso = _smooth_pose(
            self._current_torso,
            torso_target,
            position_alpha=0.0,
            rotation_alpha=self._settings.torso_rotation_smoothing,
        )
        left_bone_scales = calib.left_arm_bone_scales
        right_bone_scales = calib.right_arm_bone_scales
        left_twist_rad: float | None = None
        right_twist_rad: float | None = None
        if self._settings.wrist_orientation_mode == "twist":
            # Choose the equivalent source angle nearest the previous bounded
            # target, then clamp and slew it. This crosses +/-pi continuously
            # without accumulating turns that G1 cannot represent.
            left_twist_rad = self._left_arm.apply_bound_twist(
                _wrist_twist_delta_rad(torso, left, calib.torso, calib.left),
            )
            right_twist_rad = self._right_arm.apply_bound_twist(
                _wrist_twist_delta_rad(torso, right, calib.torso, calib.right),
            )
        if self._ik_config is not None:
            if left_bone_scales is None or right_bone_scales is None:
                raise RuntimeError("declarative IK config is missing calibrated scales")
            aligned_positions = _aligned_skeleton_positions(
                frame, self._settings, _calibration_view_from_state(calib)
            )
            left_shoulder_position = aligned_positions.get(int(BodyJoint.LEFT_SHOULDER))
            right_shoulder_position = aligned_positions.get(
                int(BodyJoint.RIGHT_SHOULDER)
            )
            if left_shoulder_position is None or right_shoulder_position is None:
                return None
            left_targets = _declarative_arm_targets(
                torso=torso,
                arm=left,
                neutral_torso=calib.torso,
                neutral=calib.left,
                settings=self._settings,
                is_left=True,
                bone_scales=left_bone_scales,
                config=self._ik_config,
                bounded_twist_rad=left_twist_rad,
                shoulder_position=left_shoulder_position,
            )
            right_targets = _declarative_arm_targets(
                torso=torso,
                arm=right,
                neutral_torso=calib.torso,
                neutral=calib.right,
                settings=self._settings,
                is_left=False,
                bone_scales=right_bone_scales,
                config=self._ik_config,
                bounded_twist_rad=right_twist_rad,
                shoulder_position=right_shoulder_position,
            )
            self._left_arm.update_wrist(left_targets.wrist)
            self._right_arm.update_wrist(right_targets.wrist)
            if self._settings.track_elbow_ik_targets:
                self._left_arm.update_elbow(left_targets.elbow)
                self._right_arm.update_elbow(right_targets.elbow)
            if self._settings.track_shoulder_ik_targets:
                self._left_arm.update_shoulder(left_targets.shoulder)
                self._right_arm.update_shoulder(right_targets.shoulder)
            return self.current_arm_targets

        if self._settings.track_aligned_mocap_wrists:
            left_target = _wrist_target_from_aligned_skeleton(
                frame,
                calib,
                self._settings,
                is_left=True,
            )
            right_target = _wrist_target_from_aligned_skeleton(
                frame,
                calib,
                self._settings,
                is_left=False,
            )
            if left_target is None or right_target is None:
                return None
            left_forearm = _aligned_forearm_direction(
                frame, calib, self._settings, is_left=True
            )
            right_forearm = _aligned_forearm_direction(
                frame, calib, self._settings, is_left=False
            )
            left_target.quaternion_xyzw = _tracked_wrist_quaternion(
                torso,
                left,
                calib.torso,
                calib.left,
                calib.nominal_left.quaternion_xyzw,
                calib.neutral_left_forearm_robot,
                left_forearm,
                self._settings,
                bounded_twist_rad=left_twist_rad,
            )
            right_target.quaternion_xyzw = _tracked_wrist_quaternion(
                torso,
                right,
                calib.torso,
                calib.right,
                calib.nominal_right.quaternion_xyzw,
                calib.neutral_right_forearm_robot,
                right_forearm,
                self._settings,
                bounded_twist_rad=right_twist_rad,
            )
        else:
            left_target = _solve_wrist_target(
                torso=torso,
                arm=left,
                pelvis_world=pelvis_world,
                neutral=calib.left,
                neutral_torso=calib.torso,
                nominal=calib.nominal_left,
                neutral_forearm_robot=calib.neutral_left_forearm_robot,
                calib_yaw=calib.body_yaw_isaac,
                arm_length_scale=calib.arm_length_scale,
                settings=self._settings,
                is_left=True,
                bounded_twist_rad=left_twist_rad,
                bone_scales=left_bone_scales,
            )
            right_target = _solve_wrist_target(
                torso=torso,
                arm=right,
                pelvis_world=pelvis_world,
                neutral=calib.right,
                neutral_torso=calib.torso,
                nominal=calib.nominal_right,
                neutral_forearm_robot=calib.neutral_right_forearm_robot,
                calib_yaw=calib.body_yaw_isaac,
                arm_length_scale=calib.arm_length_scale,
                settings=self._settings,
                is_left=False,
                bounded_twist_rad=right_twist_rad,
                bone_scales=right_bone_scales,
            )
        self._left_arm.update_wrist(left_target)
        self._right_arm.update_wrist(right_target)

        if self._settings.track_elbow_ik_targets:
            if self._settings.track_aligned_mocap_wrists:
                left_elbow_target = _elbow_target_from_aligned_skeleton(
                    frame, calib, self._settings, is_left=True
                )
                right_elbow_target = _elbow_target_from_aligned_skeleton(
                    frame, calib, self._settings, is_left=False
                )
            else:
                yaw_delta = _resolve_yaw_delta(
                    _compute_torso_yaw(torso) - calib.body_yaw_isaac, self._settings
                )
                left_elbow_target = _solve_elbow_target(
                    arm=left,
                    neutral=calib.left,
                    nominal=calib.nominal_left_elbow,
                    settings=self._settings,
                    yaw_delta=yaw_delta,
                    is_left=True,
                    bone_scales=left_bone_scales,
                )
                right_elbow_target = _solve_elbow_target(
                    arm=right,
                    neutral=calib.right,
                    nominal=calib.nominal_right_elbow,
                    settings=self._settings,
                    yaw_delta=yaw_delta,
                    is_left=False,
                    bone_scales=right_bone_scales,
                )
            if left_elbow_target is None or right_elbow_target is None:
                return None
            self._left_arm.update_elbow(left_elbow_target)
            self._right_arm.update_elbow(right_elbow_target)

        if self._settings.track_shoulder_ik_targets:
            if self._settings.track_aligned_mocap_wrists:
                left_shoulder_target = _shoulder_target_from_aligned_skeleton(
                    frame, calib, self._settings, is_left=True
                )
                right_shoulder_target = _shoulder_target_from_aligned_skeleton(
                    frame, calib, self._settings, is_left=False
                )
            else:
                yaw_delta = _resolve_yaw_delta(
                    _compute_torso_yaw(torso) - calib.body_yaw_isaac, self._settings
                )
                left_shoulder_target = _solve_shoulder_target(
                    arm=left,
                    neutral=calib.left,
                    nominal=calib.nominal_left_shoulder,
                    settings=self._settings,
                    yaw_delta=yaw_delta,
                    is_left=True,
                    bone_scales=left_bone_scales,
                )
                right_shoulder_target = _solve_shoulder_target(
                    arm=right,
                    neutral=calib.right,
                    nominal=calib.nominal_right_shoulder,
                    settings=self._settings,
                    yaw_delta=yaw_delta,
                    is_left=False,
                    bone_scales=right_bone_scales,
                )
            if left_shoulder_target is None or right_shoulder_target is None:
                return None
            self._left_arm.update_shoulder(left_shoulder_target)
            self._right_arm.update_shoulder(right_shoulder_target)

        return self.current_arm_targets

    def input_spec(self) -> RetargeterIOType:
        return {"full_body_tracked": DeviceIOFullBodyPoseTracked()}

    def output_spec(self) -> RetargeterIOType:
        wrist_type = NDArrayType(
            "pose", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32
        )
        return {
            "left_wrist": TensorGroupType("left_wrist", [wrist_type]),
            "right_wrist": TensorGroupType("right_wrist", [wrist_type]),
            "body_yaw_delta": TensorGroupType(
                "body_yaw_delta",
                [NDArrayType("yaw", shape=(1,), dtype=DLDataType.FLOAT, dtype_bits=32)],
            ),
        }

    def _compute_fn(
        self,
        inputs: RetargeterIO,
        outputs: RetargeterIO,
        context: ComputeContext,
    ) -> None:
        if context.execution_events.reset:
            self.clear_calibration()

        frame = inputs["full_body_tracked"][0]

        if frame is not None:
            if self._calibration is None:
                self.calibrate(frame)
            else:
                self.retarget(frame)

        outputs["left_wrist"][0] = self._left_arm.current_wrist.as_action_pose()
        outputs["right_wrist"][0] = self._right_arm.current_wrist.as_action_pose()
        outputs["body_yaw_delta"][0] = np.float32(self.body_yaw_delta)


def noitom_position_to_isaac(position: np.ndarray) -> np.ndarray:
    """Convert a Noitom Y-up position vector to Isaac Z-up."""
    return (_NOITOM_TO_ISAAC @ np.asarray(position, dtype=np.float64)).astype(
        np.float64
    )


def noitom_quaternion_to_isaac(quaternion_xyzw: np.ndarray) -> np.ndarray:
    """Convert a Noitom Y-up quaternion (xyzw) to Isaac Z-up."""
    rot = Rotation.from_quat(_normalize_quat(quaternion_xyzw))
    return _normalize_quat((_COORD_ROT * rot * _COORD_ROT.inv()).as_quat())


def map_point_to_robot_frame(
    noitom_point_yup: np.ndarray,
    pelvis_yup: np.ndarray,
    calib: NoitomCalibrationView | None,
    current_yaw: float,
    robot_pelvis: np.ndarray,
    draw_scale: float = 1.0,
    *,
    operator_faces_robot: bool = True,
    length_scale: float | None = None,
) -> np.ndarray:
    """Map a Noitom joint position into the robot simulation frame for debug draw."""
    point = noitom_position_to_isaac(noitom_point_yup)
    pelvis = noitom_position_to_isaac(pelvis_yup)
    rel = point - pelvis
    if calib is None:
        offset = rel * draw_scale
        if operator_faces_robot:
            offset = Rotation.from_euler("z", np.pi).apply(offset)
        return robot_pelvis + offset
    yaw_delta = current_yaw - calib.body_yaw_isaac
    scale = calib.arm_length_scale if length_scale is None else length_scale
    offset = _map_mocap_rel_to_robot_offset(
        rel,
        scale,
        draw_scale,
        yaw_delta,
        operator_faces_robot,
    )
    return robot_pelvis + offset


def _normalize_quat(quat_xyzw: np.ndarray) -> np.ndarray:
    quat = np.asarray(quat_xyzw, dtype=np.float64)
    norm = np.linalg.norm(quat)
    if norm < 1e-8:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
    return quat / norm


def _point_to_array(point: Any) -> np.ndarray:
    return np.array([point.x, point.y, point.z], dtype=np.float64)


def _quat_to_array(point: Any) -> np.ndarray:
    return _normalize_quat(
        np.array([point.x, point.y, point.z, point.w], dtype=np.float64)
    )


def _joint_pose(frame: Any, joint_index: BodyJoint | int) -> SE3Pose | None:
    if frame.joints is None:
        return None
    joint = frame.joints.joints(int(joint_index))
    if not joint.is_valid:
        return None
    pos = _point_to_array(joint.pose.position)
    quat = _quat_to_array(joint.pose.orientation)
    if not np.all(np.isfinite(pos)) or not np.all(np.isfinite(quat)):
        return None
    return SE3Pose(
        noitom_position_to_isaac(pos),
        noitom_quaternion_to_isaac(quat),
    )


def _build_torso_frame(frame: Any) -> _TorsoFrame | None:
    pelvis = _joint_pose(frame, BodyJoint.PELVIS)
    spine = _joint_pose(frame, BodyJoint.SPINE3)
    left_shoulder = _joint_pose(frame, BodyJoint.LEFT_SHOULDER)
    right_shoulder = _joint_pose(frame, BodyJoint.RIGHT_SHOULDER)
    if (
        pelvis is None
        or spine is None
        or left_shoulder is None
        or right_shoulder is None
    ):
        return None

    up = spine.position - pelvis.position
    right = right_shoulder.position - left_shoulder.position
    if np.linalg.norm(up) < 1e-5 or np.linalg.norm(right) < 1e-5:
        return None
    up /= np.linalg.norm(up)
    right /= np.linalg.norm(right)
    forward = np.cross(up, right)
    if np.linalg.norm(forward) < 1e-5:
        return None
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    rotation = Rotation.from_matrix(np.column_stack([right, forward, up]))
    return _TorsoFrame(origin=spine.position.copy(), rotation=rotation)


def _compute_torso_yaw(torso: _TorsoFrame) -> float:
    forward = torso.rotation.as_matrix()[:, 1]
    return float(np.arctan2(forward[1], forward[0]))


def _reference_alignment_rotation(torso: _TorsoFrame) -> Rotation:
    """Yaw-align raw source frames with the cyan skeleton facing G1 world +Y."""
    return Rotation.from_euler("z", np.pi * 0.5 - _compute_torso_yaw(torso))


def _torso_target_from_relative_motion(
    torso: _TorsoFrame,
    neutral_torso: _TorsoFrame,
    settings: NoitomRetargetingSettings,
) -> SE3Pose:
    """Map calibration-relative torso orientation into the fixed G1 pelvis frame."""
    relative = neutral_torso.rotation.inv() * torso.rotation

    yaw_roll_pitch = relative.as_euler("ZXY") * settings.torso_orientation_scale
    limits = np.deg2rad(
        [
            settings.torso_yaw_limit_deg,
            settings.torso_roll_limit_deg,
            settings.torso_pitch_limit_deg,
        ]
    )
    bounded = np.clip(yaw_roll_pitch, -limits, limits)
    pelvis_world_rotation = Rotation.from_quat(
        _normalize_quat(settings.robot_pelvis_quat_xyzw)
    )
    quaternion = _normalize_quat(
        (pelvis_world_rotation * Rotation.from_euler("ZXY", bounded)).as_quat()
    )
    return SE3Pose(settings.robot_pelvis_world.astype(np.float64).copy(), quaternion)


def _aligned_source_wrist_rotation(
    torso: _TorsoFrame, arm: _ArmCalibration
) -> Rotation:
    """Place one BVH wrist world frame in the cyan skeleton's robot alignment."""
    wrist_world = torso.rotation * arm.wrist_rot_torso
    return _reference_alignment_rotation(torso) * wrist_world


def _semantic_source_wrist_rotation(
    aligned_raw: Rotation, local_offset_xyzw: np.ndarray
) -> Rotation:
    """Apply one normalized BVH-local post-rotation to an aligned raw wrist."""
    return aligned_raw * Rotation.from_quat(_normalize_quat(local_offset_xyzw))


def _pose_to_torso(pose: SE3Pose, torso: _TorsoFrame) -> tuple[np.ndarray, Rotation]:
    pos_torso = torso.rotation.inv().apply(pose.position - torso.origin)
    rot_torso = torso.rotation.inv() * Rotation.from_quat(pose.quaternion_xyzw)
    return pos_torso, rot_torso


def _parse_arm(
    frame: Any,
    torso: _TorsoFrame,
    pelvis_world: np.ndarray,
    shoulder_index: BodyJoint,
    elbow_index: BodyJoint,
    wrist_index: BodyJoint,
) -> _ArmCalibration | None:
    shoulder = _joint_pose(frame, shoulder_index)
    elbow = _joint_pose(frame, elbow_index)
    wrist = _joint_pose(frame, wrist_index)
    if shoulder is None or elbow is None or wrist is None:
        return None

    upper_arm_length = float(np.linalg.norm(elbow.position - shoulder.position))
    forearm_length = float(np.linalg.norm(wrist.position - elbow.position))
    if upper_arm_length < 1e-4 or forearm_length < 1e-4:
        return None

    wrist_pos_torso, wrist_rot_torso = _pose_to_torso(wrist, torso)
    shoulder_torso = torso.rotation.inv().apply(shoulder.position - torso.origin)
    wrist_rel_pelvis = wrist.position - pelvis_world
    return _ArmCalibration(
        shoulder_torso=shoulder_torso,
        shoulder_world=shoulder.position.copy(),
        elbow_world=elbow.position.copy(),
        wrist_pos_torso=wrist_pos_torso,
        wrist_rot_torso=wrist_rot_torso,
        wrist_rel_pelvis=wrist_rel_pelvis,
        wrist_world=wrist.position.copy(),
        upper_arm_length=upper_arm_length,
        forearm_length=forearm_length,
    )


def _parse_upper_body(
    frame: Any,
) -> tuple[_TorsoFrame, _ArmCalibration, _ArmCalibration, np.ndarray] | None:
    pelvis_pose = _joint_pose(frame, BodyJoint.PELVIS)
    torso = _build_torso_frame(frame)
    if pelvis_pose is None or torso is None:
        return None
    pelvis_world = pelvis_pose.position.copy()
    left = _parse_arm(
        frame,
        torso,
        pelvis_world,
        BodyJoint.LEFT_SHOULDER,
        BodyJoint.LEFT_ELBOW,
        BodyJoint.LEFT_WRIST,
    )
    right = _parse_arm(
        frame,
        torso,
        pelvis_world,
        BodyJoint.RIGHT_SHOULDER,
        BodyJoint.RIGHT_ELBOW,
        BodyJoint.RIGHT_WRIST,
    )
    if left is None or right is None:
        return None
    return torso, left, right, pelvis_world


def _resolve_yaw_delta(yaw_delta: float, settings: NoitomRetargetingSettings) -> float:
    """Limit torso twist fed into arm FK (prevents waist+arm IK deadlock)."""
    influenced = yaw_delta * settings.torso_yaw_arm_influence
    limit = settings.max_torso_yaw_delta
    return float(np.clip(influenced, -limit, limit))


def _map_mocap_direction_to_robot(
    direction_isaac: np.ndarray,
    yaw_delta: float,
    operator_faces_robot: bool,
) -> np.ndarray:
    """Rotate a unit bone direction from mocap into the robot frame (no length scale)."""
    direction = np.asarray(direction_isaac, dtype=np.float64)
    norm = float(np.linalg.norm(direction))
    if norm < 1e-6:
        return np.array([1.0, 0.0, 0.0], dtype=np.float64)
    direction = direction / norm
    if operator_faces_robot:
        direction = Rotation.from_euler("z", np.pi).apply(direction)
    return Rotation.from_euler("z", yaw_delta).apply(direction)


def _shoulder_world_robot(
    settings: NoitomRetargetingSettings,
    yaw_delta: float,
    is_left: bool,
) -> np.ndarray:
    anchor = settings.robot_pelvis_world.astype(np.float64)
    return anchor + _shoulder_offset_robot(settings, yaw_delta, is_left)


def _arm_fk_robot(
    arm: _ArmCalibration,
    settings: NoitomRetargetingSettings,
    yaw_delta: float,
    is_left: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """FK along mocap bone directions using G1 upper-arm and forearm lengths."""
    shoulder_robot = _shoulder_world_robot(settings, yaw_delta, is_left)
    upper_dir = _map_mocap_direction_to_robot(
        arm.elbow_world - arm.shoulder_world,
        yaw_delta,
        settings.operator_faces_robot,
    )
    forearm_dir = _map_mocap_direction_to_robot(
        arm.wrist_world - arm.elbow_world,
        yaw_delta,
        settings.operator_faces_robot,
    )
    upper_len = settings.robot_upper_arm_length
    forearm_len = settings.robot_forearm_length
    elbow_robot = shoulder_robot + upper_dir * upper_len
    wrist_robot = elbow_robot + forearm_dir * forearm_len
    return shoulder_robot, elbow_robot, wrist_robot


def _slerp_unit_direction(
    neutral_dir: np.ndarray, full_dir: np.ndarray, blend: float
) -> np.ndarray:
    """Interpolate unit bone directions (keeps FK chain valid after FK)."""
    t = float(np.clip(blend, 0.0, 1.0))
    mixed = (1.0 - t) * neutral_dir + t * full_dir
    norm = float(np.linalg.norm(mixed))
    if norm < 1e-6:
        return full_dir
    return mixed / norm


def _arm_direction_dot(upper_dir: np.ndarray, forearm_dir: np.ndarray) -> float:
    return float(np.dot(upper_dir, forearm_dir))


def _unit_direction(
    vector: np.ndarray, fallback: np.ndarray | None = None
) -> np.ndarray:
    vec = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(vec))
    if norm < 1e-6:
        if fallback is not None:
            return _unit_direction(fallback)
        return np.array([1.0, 0.0, 0.0], dtype=np.float64)
    return vec / norm


def _interpolate_shortest_arc_direction(
    neutral_direction: np.ndarray,
    current_direction: np.ndarray,
    amount: float,
) -> np.ndarray:
    """Apply a fraction of the shortest neutral-to-current bone rotation."""
    neutral = _unit_direction(neutral_direction)
    current = _unit_direction(current_direction, fallback=neutral)
    delta = _shortest_arc_rotation(neutral, current)
    fraction = float(np.clip(amount, 0.0, 1.0))
    return _unit_direction(
        Rotation.from_rotvec(delta.as_rotvec() * fraction).apply(neutral),
        fallback=neutral,
    )


def _pose_with_mapping_offset(
    position: np.ndarray,
    quaternion_xyzw: np.ndarray,
    mapping: NoitomIkMatch,
) -> SE3Pose:
    """Apply a GMR-style local position offset to one configured target pose."""
    rotation = Rotation.from_quat(_normalize_quat(quaternion_xyzw))
    target_position = np.asarray(position, dtype=np.float64) + rotation.apply(
        mapping.position_offset
    )
    return SE3Pose(target_position, _normalize_quat(rotation.as_quat()))


def _declarative_arm_targets(
    *,
    torso: _TorsoFrame,
    arm: _ArmCalibration,
    neutral_torso: _TorsoFrame,
    neutral: _ArmCalibration,
    settings: NoitomRetargetingSettings,
    is_left: bool,
    bone_scales: _ArmBoneScales,
    config: NoitomIkConfig,
    bounded_twist_rad: float | None,
    shoulder_position: np.ndarray,
) -> _DeclarativeArmTargets:
    """Solve one arm from the validated mapping table and calibrated bone vectors.

    The position solve is deliberately generic: rotate each neutral human bone
    direction along its shortest arc toward the current direction, apply the
    configured motion fraction, then rebuild the chain with the per-segment scale
    table. Pink consumes the configured target weights downstream.
    """
    side = "left" if is_left else "right"
    yaw_delta = _resolve_yaw_delta(
        _compute_torso_yaw(torso) - _compute_torso_yaw(neutral_torso), settings
    )
    neutral_alignment = _reference_alignment_rotation(neutral_torso)
    current_alignment = _reference_alignment_rotation(torso)
    yaw_rotation = Rotation.from_euler("z", yaw_delta)
    neutral_upper = neutral_alignment.apply(
        neutral.elbow_world - neutral.shoulder_world
    )
    current_upper = yaw_rotation.apply(
        current_alignment.apply(arm.elbow_world - arm.shoulder_world)
    )
    neutral_forearm = neutral_alignment.apply(neutral.wrist_world - neutral.elbow_world)
    current_forearm = yaw_rotation.apply(
        current_alignment.apply(arm.wrist_world - arm.elbow_world)
    )
    upper_direction = _interpolate_shortest_arc_direction(
        neutral_upper, current_upper, settings.motion_scale
    )
    forearm_direction = _interpolate_shortest_arc_direction(
        neutral_forearm, current_forearm, settings.motion_scale
    )

    shoulder_mapping = config.match(side, "shoulder")
    elbow_mapping = config.match(side, "elbow")
    wrist_mapping = config.match(side, "wrist")
    shoulder_position = np.asarray(shoulder_position, dtype=np.float64)
    elbow_position = shoulder_position + upper_direction * bone_scales.upper_arm
    wrist_position = elbow_position + forearm_direction * bone_scales.forearm

    shoulder_pose = _pose_with_mapping_offset(
        shoulder_position,
        shoulder_mapping.rotation_offset_xyzw,
        shoulder_mapping,
    )
    elbow_pose = _pose_with_mapping_offset(
        elbow_position,
        elbow_mapping.rotation_offset_xyzw,
        elbow_mapping,
    )
    # The mapping offset normalizes BVH anatomy only for direct source tracking.
    # Compatibility modes used identity here before the semantic-frame correction.
    compatibility_nominal = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
    wrist_quaternion = _tracked_wrist_quaternion(
        torso,
        arm,
        neutral_torso,
        neutral,
        compatibility_nominal,
        neutral_forearm,
        forearm_direction,
        settings,
        bounded_twist_rad=bounded_twist_rad,
        source_local_offset_xyzw=wrist_mapping.rotation_offset_xyzw,
    )
    wrist_pose = _pose_with_mapping_offset(
        wrist_position,
        wrist_quaternion,
        wrist_mapping,
    )
    return _DeclarativeArmTargets(
        shoulder=shoulder_pose,
        elbow=elbow_pose,
        wrist=wrist_pose,
    )


def _elbow_interior_angle(upper_dir: np.ndarray, forearm_dir: np.ndarray) -> float:
    """Angle (rad) between upper-arm and forearm unit directions; 0 = fully extended."""
    dot = float(
        np.clip(
            _arm_direction_dot(
                _unit_direction(upper_dir), _unit_direction(forearm_dir)
            ),
            -1.0,
            1.0,
        )
    )
    return float(np.arccos(dot))


def _forearm_dir_from_elbow_angle(
    upper_dir: np.ndarray,
    forearm_hint: np.ndarray,
    elbow_angle: float,
) -> np.ndarray:
    """Rebuild a forearm unit vector with the given interior elbow angle."""
    upper = _unit_direction(upper_dir)
    hint = _unit_direction(forearm_hint, fallback=upper)
    perp = hint - upper * float(np.dot(hint, upper))
    perp_norm = float(np.linalg.norm(perp))
    if perp_norm < 1e-6:
        perp = np.cross(upper, np.array([0.0, 0.0, 1.0], dtype=np.float64))
        perp_norm = float(np.linalg.norm(perp))
        if perp_norm < 1e-6:
            perp = np.cross(upper, np.array([0.0, 1.0, 0.0], dtype=np.float64))
            perp_norm = float(np.linalg.norm(perp))
    perp = perp / max(perp_norm, 1e-8)
    angle = float(np.clip(elbow_angle, 0.0, np.pi - 1e-3))
    forearm = np.cos(angle) * upper + np.sin(angle) * perp
    return _unit_direction(forearm, fallback=upper)


def _human_robot_reach_scale(
    arm: _ArmCalibration,
    settings: NoitomRetargetingSettings,
    bone_scales: _ArmBoneScales | None = None,
) -> float:
    """Shrink motion when the operator arm is longer than the active robot chain."""
    human_reach = arm.upper_arm_length + arm.forearm_length
    if bone_scales is not None:
        robot_reach = bone_scales.upper_arm + bone_scales.forearm
    else:
        robot_reach = settings.robot_upper_arm_length + settings.robot_forearm_length
    if human_reach <= robot_reach + 1e-4:
        return 1.0
    return float(
        np.clip(robot_reach * settings.human_reach_margin / human_reach, 0.25, 1.0)
    )


def _effective_motion_scale(
    base_scale: float, extension_dot: float, soft_limit: float
) -> float:
    """Shrink motion when the target arm chain is near full extension."""
    scale = float(np.clip(base_scale, 0.0, 1.0))
    if extension_dot <= soft_limit:
        return scale
    penalty = (extension_dot - soft_limit) / max(1e-3, 1.0 - soft_limit)
    return scale * (1.0 - 0.7 * float(np.clip(penalty, 0.0, 1.0)))


def _bend_forearm_direction(
    upper_dir: np.ndarray, forearm_dir: np.ndarray, target_dot: float = 0.55
) -> np.ndarray:
    """Pull forearm direction off a straight line to avoid elbow singularities."""
    upper = upper_dir / (np.linalg.norm(upper_dir) + 1e-8)
    forearm = forearm_dir / (np.linalg.norm(forearm_dir) + 1e-8)
    if _arm_direction_dot(upper, forearm) <= target_dot:
        return forearm
    axis = np.cross(upper, np.array([0.0, 0.0, 1.0], dtype=np.float64))
    if float(np.linalg.norm(axis)) < 1e-4:
        axis = np.cross(upper, np.array([0.0, 1.0, 0.0], dtype=np.float64))
    axis = axis / (np.linalg.norm(axis) + 1e-8)
    bent = forearm.copy()
    for _ in range(8):
        if _arm_direction_dot(upper, bent) <= target_dot:
            break
        bent = Rotation.from_rotvec(axis * 0.12).apply(bent)
        bent = bent / (np.linalg.norm(bent) + 1e-8)
    return bent


def _arm_chain_from_directions(
    shoulder_robot: np.ndarray,
    upper_dir: np.ndarray,
    forearm_dir: np.ndarray,
    settings: NoitomRetargetingSettings,
    bone_scales: _ArmBoneScales | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Run arm FK along unit bone directions using active robot link lengths."""
    if bone_scales is not None:
        upper_len = bone_scales.upper_arm
        forearm_len = bone_scales.forearm
    else:
        upper_len = settings.robot_upper_arm_length
        forearm_len = settings.robot_forearm_length
    elbow = shoulder_robot + upper_dir * upper_len
    wrist = elbow + forearm_dir * forearm_len
    wrist = _clamp_reach(shoulder_robot, wrist, upper_len, forearm_len)
    fore_vec = wrist - elbow
    fore_dist = float(np.linalg.norm(fore_vec))
    if fore_dist > 1e-6 and fore_dist > forearm_len:
        wrist = elbow + fore_vec * (forearm_len / fore_dist)
    return elbow, wrist


def _arm_fk_robot_blended(
    arm: _ArmCalibration,
    neutral_arm: _ArmCalibration,
    settings: NoitomRetargetingSettings,
    yaw_delta: float,
    is_left: bool,
    bone_scales: _ArmBoneScales | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Blend mocap posture, then run FK with the active arm link lengths."""
    shoulder_robot = _shoulder_world_robot(settings, yaw_delta, is_left)
    upper_n = _map_mocap_direction_to_robot(
        neutral_arm.elbow_world - neutral_arm.shoulder_world,
        yaw_delta,
        settings.operator_faces_robot,
    )
    upper_f = _map_mocap_direction_to_robot(
        arm.elbow_world - arm.shoulder_world,
        yaw_delta,
        settings.operator_faces_robot,
    )
    fore_n = _map_mocap_direction_to_robot(
        neutral_arm.wrist_world - neutral_arm.elbow_world,
        yaw_delta,
        settings.operator_faces_robot,
    )
    fore_f = _map_mocap_direction_to_robot(
        arm.wrist_world - arm.elbow_world,
        yaw_delta,
        settings.operator_faces_robot,
    )
    scale = _effective_motion_scale(
        settings.motion_scale,
        _arm_direction_dot(upper_f, fore_f),
        settings.arm_extension_soft_limit,
    )
    yaw_factor = 1.0 - 0.45 * min(
        1.0, abs(yaw_delta) / max(settings.max_torso_yaw_delta, 1e-3)
    )
    scale *= max(0.25, yaw_factor)
    scale *= _human_robot_reach_scale(arm, settings, bone_scales=bone_scales)
    upper_d = _slerp_unit_direction(upper_n, upper_f, scale)

    theta_n = _elbow_interior_angle(upper_n, fore_n)
    theta_f = _elbow_interior_angle(upper_f, fore_f)
    theta_d = (1.0 - scale) * theta_n + scale * theta_f
    min_theta = max(
        settings.min_elbow_interior_angle,
        float(np.arccos(np.clip(settings.arm_extension_soft_limit, -1.0, 1.0))),
    )
    theta_d = float(np.clip(max(theta_d, min_theta), min_theta, np.pi - 1e-3))
    fore_d = _forearm_dir_from_elbow_angle(upper_d, fore_f, theta_d)

    if _arm_direction_dot(upper_d, fore_d) > settings.arm_extension_soft_limit:
        fore_d = _bend_forearm_direction(upper_d, fore_d)

    elbow_neutral, wrist_neutral = _arm_chain_from_directions(
        shoulder_robot, upper_n, fore_n, settings, bone_scales=bone_scales
    )
    elbow_full, wrist_full = _arm_chain_from_directions(
        shoulder_robot, upper_d, fore_d, settings, bone_scales=bone_scales
    )
    elbow_robot = elbow_neutral + scale * (elbow_full - elbow_neutral)
    wrist_robot = wrist_neutral + scale * (wrist_full - wrist_neutral)
    if bone_scales is not None:
        wrist_robot = _clamp_reach(
            shoulder_robot,
            wrist_robot,
            bone_scales.upper_arm,
            bone_scales.forearm,
        )
    else:
        wrist_robot = _clamp_reach(
            shoulder_robot,
            wrist_robot,
            settings.robot_upper_arm_length,
            settings.robot_forearm_length,
        )
    return shoulder_robot, elbow_robot, wrist_robot


def _wrist_quat_from_forearm(
    forearm_dir: np.ndarray,
    nominal_quat: np.ndarray,
    blend: float,
) -> np.ndarray:
    """Derive a wrist quaternion consistent with the solved forearm direction."""
    forward = np.asarray(forearm_dir, dtype=np.float64)
    norm = float(np.linalg.norm(forward))
    if norm < 1e-6:
        return _normalize_quat(nominal_quat)
    forward = forward / norm
    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    if abs(float(np.dot(forward, world_up))) > 0.92:
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    right = np.cross(forward, world_up)
    right_norm = float(np.linalg.norm(right))
    if right_norm < 1e-6:
        return _normalize_quat(nominal_quat)
    right = right / right_norm
    up = np.cross(right, forward)
    aligned = Rotation.from_matrix(np.column_stack([right, forward, up]))
    blend_clamped = float(np.clip(blend, 0.0, 1.0))
    if blend_clamped <= 0.0:
        return _normalize_quat(nominal_quat)
    if blend_clamped >= 1.0:
        return _normalize_quat(aligned.as_quat())
    nominal_rot = Rotation.from_quat(nominal_quat)
    slerp = Slerp(
        [0.0, 1.0],
        Rotation.concatenate([nominal_rot, aligned]),
    )
    return _normalize_quat(slerp([blend_clamped]).as_quat()[0])


def _wrist_pose_from_posture(
    arm: _ArmCalibration,
    settings: NoitomRetargetingSettings,
    is_left: bool,
    yaw_delta: float,
    nominal_quat: np.ndarray,
) -> SE3Pose:
    _shoulder_robot, _elbow_robot, wrist_robot = _arm_fk_robot(
        arm, settings, yaw_delta, is_left
    )
    forearm_dir = _map_mocap_direction_to_robot(
        arm.wrist_world - arm.elbow_world,
        yaw_delta,
        settings.operator_faces_robot,
    )
    quat = _wrist_quat_for_ik(
        forearm_dir, nominal_quat, settings, track_orientation=False
    )
    return SE3Pose(wrist_robot, quat)


def _wrist_quat_for_ik(
    forearm_dir: np.ndarray,
    nominal_quat: np.ndarray,
    settings: NoitomRetargetingSettings,
    track_orientation: bool,
) -> np.ndarray:
    if track_orientation:
        return _normalize_quat(nominal_quat)
    return _wrist_quat_from_forearm(
        forearm_dir,
        nominal_quat,
        settings.wrist_orientation_forearm_blend,
    )


def _tracked_wrist_quaternion(
    torso: _TorsoFrame,
    arm: _ArmCalibration,
    neutral_torso: _TorsoFrame,
    neutral: _ArmCalibration,
    nominal_quat: np.ndarray,
    neutral_target_forearm_dir: np.ndarray,
    target_forearm_dir: np.ndarray,
    settings: NoitomRetargetingSettings,
    bounded_twist_rad: float | None = None,
    source_local_offset_xyzw: np.ndarray | None = None,
) -> np.ndarray:
    """Parallel-transport neutral orientation, then add residual source roll."""
    if settings.wrist_orientation_mode == "source":
        local_offset = (
            np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
            if source_local_offset_xyzw is None
            else _normalize_quat(source_local_offset_xyzw)
        )
        target_rot = _semantic_source_wrist_rotation(
            _aligned_source_wrist_rotation(torso, arm), local_offset
        )
        return _normalize_quat(target_rot.as_quat())

    wrist_world_rot = torso.rotation * arm.wrist_rot_torso
    wrist_neutral_world_rot = neutral_torso.rotation * neutral.wrist_rot_torso
    nominal_rot = Rotation.from_quat(nominal_quat)
    if settings.wrist_orientation_mode == "full":
        delta_rot_world = wrist_world_rot * wrist_neutral_world_rot.inv()
        target_rot = delta_rot_world * nominal_rot
        return _normalize_quat(target_rot.as_quat())

    # Do not rebuild a forearm frame from world-up or blend the calibrated
    # nominal again: arms-down makes that frame singular and repeated blending
    # creates a target jump even when the source pose is unchanged.
    target_swing = _shortest_arc_rotation(
        neutral_target_forearm_dir,
        target_forearm_dir,
        fallback_axis=nominal_rot.apply(np.array([1.0, 0.0, 0.0])),
    )
    target_rot = target_swing * nominal_rot
    if settings.wrist_orientation_mode == "twist":
        twist_rad = bounded_twist_rad
        if twist_rad is None:
            twist_rad = _wrist_twist_delta_rad(torso, arm, neutral_torso, neutral)
        twist_rad = _clamp_wrist_twist(twist_rad, settings.wrist_twist_limit_deg)
        target_axis = _unit_direction(target_forearm_dir)
        target_rot = Rotation.from_rotvec(target_axis * twist_rad) * target_rot
    return _normalize_quat(target_rot.as_quat())


def _shortest_arc_rotation(
    from_direction: np.ndarray,
    to_direction: np.ndarray,
    fallback_axis: np.ndarray | None = None,
) -> Rotation:
    """Return the minimum rotation mapping one direction onto another."""
    source = _unit_direction(from_direction)
    target = _unit_direction(to_direction)
    dot = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if dot > 1.0 - 1e-10:
        return Rotation.identity()
    if dot < -1.0 + 1e-8:
        axis_hint = (
            np.asarray(fallback_axis, dtype=np.float64)
            if fallback_axis is not None
            else np.array([1.0, 0.0, 0.0], dtype=np.float64)
        )
        axis = axis_hint - source * float(np.dot(axis_hint, source))
        if float(np.linalg.norm(axis)) < 1e-6:
            alternate = np.array([0.0, 1.0, 0.0], dtype=np.float64)
            axis = alternate - source * float(np.dot(alternate, source))
        return Rotation.from_rotvec(_unit_direction(axis) * np.pi)
    quaternion_xyzw = np.concatenate([np.cross(source, target), [1.0 + dot]])
    return Rotation.from_quat(_normalize_quat(quaternion_xyzw))


def _signed_twist_rad(rotation: Rotation, axis: np.ndarray) -> float:
    """Extract the shortest signed quaternion twist about one unit axis."""
    quat = _normalize_quat(rotation.as_quat())
    if quat[3] < 0.0:
        quat = -quat
    unit_axis = _unit_direction(axis)
    projected = float(np.dot(quat[:3], unit_axis))
    angle = 2.0 * float(np.arctan2(projected, quat[3]))
    return float((angle + np.pi) % (2.0 * np.pi) - np.pi)


def _unwrap_angle_near(angle_rad: float, reference_rad: float | None) -> float:
    """Choose the angle's 2*pi-equivalent value nearest the previous sample."""
    if reference_rad is None:
        return float(angle_rad)
    delta = (angle_rad - reference_rad + np.pi) % (2.0 * np.pi) - np.pi
    return float(reference_rad + delta)


def _wrist_twist_delta_rad(
    torso: _TorsoFrame,
    arm: _ArmCalibration,
    neutral_torso: _TorsoFrame,
    neutral: _ArmCalibration,
) -> float:
    """Remove calibrated forearm swing, leaving pronation/supination residual."""
    wrist_world = torso.rotation * arm.wrist_rot_torso
    neutral_wrist_world = neutral_torso.rotation * neutral.wrist_rot_torso
    current_forearm = _unit_direction(arm.wrist_world - arm.elbow_world)
    forearm_swing = _source_forearm_swing_rotation(
        arm,
        neutral,
        neutral_torso,
    )
    no_twist_prediction = forearm_swing * neutral_wrist_world
    residual = wrist_world * no_twist_prediction.inv()
    return _signed_twist_rad(residual, current_forearm)


def _source_forearm_swing_rotation(
    arm: _ArmCalibration,
    neutral: _ArmCalibration,
    neutral_torso: _TorsoFrame,
) -> Rotation:
    neutral_forearm = neutral.wrist_world - neutral.elbow_world
    current_forearm = arm.wrist_world - arm.elbow_world
    return _shortest_arc_rotation(
        neutral_forearm,
        current_forearm,
        fallback_axis=neutral_torso.rotation.as_matrix()[:, 0],
    )


def _clamp_wrist_twist(twist_rad: float, limit_deg: float) -> float:
    limit_rad = float(np.deg2rad(max(0.0, limit_deg)))
    return float(np.clip(twist_rad, -limit_rad, limit_rad))


def compute_robot_reference_positions(
    frame: Any,
    settings: NoitomRetargetingSettings,
    calib: NoitomCalibrationView,
    current_yaw: float,
    neutral_left: _ArmCalibration,
    neutral_right: _ArmCalibration,
) -> dict[int, np.ndarray]:
    """Build a robot-proportioned reference skeleton (posture, not scaled joint dots)."""
    parsed = _parse_upper_body(frame)
    if parsed is None:
        return {}
    torso, left, right, _pelvis_world = parsed
    yaw_delta = _resolve_yaw_delta(current_yaw - calib.body_yaw_isaac, settings)
    anchor = settings.robot_pelvis_world.astype(np.float64)
    positions: dict[int, np.ndarray] = {int(BodyJoint.PELVIS): anchor.copy()}

    _fill_torso_reference_positions(frame, positions, anchor, yaw_delta, settings)

    for arm, neutral_arm, is_left, shoulder_idx, elbow_idx, wrist_idx, hand_idx in (
        (
            left,
            neutral_left,
            True,
            BodyJoint.LEFT_SHOULDER,
            BodyJoint.LEFT_ELBOW,
            BodyJoint.LEFT_WRIST,
            BodyJoint.LEFT_HAND,
        ),
        (
            right,
            neutral_right,
            False,
            BodyJoint.RIGHT_SHOULDER,
            BodyJoint.RIGHT_ELBOW,
            BodyJoint.RIGHT_WRIST,
            BodyJoint.RIGHT_HAND,
        ),
    ):
        shoulder_robot, elbow_robot, wrist_robot = _arm_fk_robot_blended(
            arm, neutral_arm, settings, yaw_delta, is_left
        )
        positions[int(shoulder_idx)] = shoulder_robot
        positions[int(elbow_idx)] = elbow_robot
        positions[int(wrist_idx)] = wrist_robot
        forearm = wrist_robot - elbow_robot
        forearm_norm = float(np.linalg.norm(forearm))
        if forearm_norm > 1e-6:
            forearm_dir = forearm / forearm_norm
        else:
            forearm_dir = _map_mocap_direction_to_robot(
                arm.wrist_world - arm.elbow_world,
                yaw_delta,
                settings.operator_faces_robot,
            )
        positions[int(hand_idx)] = wrist_robot + forearm_dir * _ROBOT_HAND_EXTENSION

    spine3 = positions.get(int(BodyJoint.SPINE3))
    if spine3 is not None:
        for collar_idx, shoulder_idx in (
            (BodyJoint.LEFT_COLLAR, BodyJoint.LEFT_SHOULDER),
            (BodyJoint.RIGHT_COLLAR, BodyJoint.RIGHT_SHOULDER),
        ):
            shoulder_pos = positions.get(int(shoulder_idx))
            if shoulder_pos is not None:
                positions[int(collar_idx)] = 0.5 * (spine3 + shoulder_pos)

    return positions


def _fill_torso_reference_positions(
    frame: Any,
    positions: dict[int, np.ndarray],
    anchor: np.ndarray,
    yaw_delta: float,
    settings: NoitomRetargetingSettings,
) -> None:
    chain = (
        BodyJoint.PELVIS,
        BodyJoint.SPINE1,
        BodyJoint.SPINE2,
        BodyJoint.SPINE3,
        BodyJoint.NECK,
        BodyJoint.HEAD,
    )
    segment_lengths = {
        BodyJoint.SPINE1: _ROBOT_TORSO_SEGMENT_Z,
        BodyJoint.SPINE2: _ROBOT_TORSO_SEGMENT_Z,
        BodyJoint.SPINE3: _ROBOT_TORSO_SEGMENT_Z,
        BodyJoint.NECK: _ROBOT_NECK_SEGMENT,
        BodyJoint.HEAD: _ROBOT_HEAD_SEGMENT,
    }
    prev_robot = anchor.copy()
    prev_mocap = _joint_pose(frame, BodyJoint.PELVIS)
    if prev_mocap is None:
        return
    prev_mocap_pos = prev_mocap.position.copy()
    for joint in chain[1:]:
        mocap_joint = _joint_pose(frame, joint)
        if mocap_joint is None:
            continue
        direction = _map_mocap_direction_to_robot(
            mocap_joint.position - prev_mocap_pos,
            yaw_delta,
            settings.operator_faces_robot,
        )
        seg_len = segment_lengths.get(joint, _ROBOT_TORSO_SEGMENT_Z)
        robot_pos = prev_robot + direction * seg_len
        positions[int(joint)] = robot_pos
        prev_robot = robot_pos
        prev_mocap_pos = mocap_joint.position.copy()


def _wrist_pose_from_pelvis_relative(
    wrist_rel_pelvis: np.ndarray,
    arm_length_scale: float,
    settings: NoitomRetargetingSettings,
    nominal_quat_xyzw: np.ndarray,
) -> SE3Pose:
    anchor = settings.robot_pelvis_world.astype(np.float64)
    offset = _map_mocap_rel_to_robot_offset(
        wrist_rel_pelvis,
        arm_length_scale,
        settings.motion_scale,
        0.0,
        settings.operator_faces_robot,
    )
    position = anchor + offset
    quat = _normalize_quat(nominal_quat_xyzw)
    return SE3Pose(position, quat)


def _map_mocap_rel_to_robot_offset(
    rel_isaac: np.ndarray,
    arm_length_scale: float,
    motion_scale: float,
    yaw_delta: float,
    operator_faces_robot: bool,
) -> np.ndarray:
    """Map a pelvis-relative mocap vector into robot pelvis-relative offset."""
    rel = np.asarray(rel_isaac, dtype=np.float64) * arm_length_scale * motion_scale
    if operator_faces_robot:
        rel = Rotation.from_euler("z", np.pi).apply(rel)
    return Rotation.from_euler("z", yaw_delta).apply(rel)


def _shoulder_offset_robot(
    settings: NoitomRetargetingSettings,
    yaw_delta: float,
    is_left: bool,
) -> np.ndarray:
    offset = (
        settings.robot_left_shoulder_offset
        if is_left
        else settings.robot_right_shoulder_offset
    )
    return Rotation.from_euler("z", yaw_delta).apply(
        np.asarray(offset, dtype=np.float64)
    )


def _clamp_reach(
    shoulder_torso: np.ndarray,
    target_torso: np.ndarray,
    upper_len: float,
    forearm_len: float,
) -> np.ndarray:
    offset = target_torso - shoulder_torso
    distance = float(np.linalg.norm(offset))
    max_reach = (upper_len + forearm_len) * 0.98
    min_reach = abs(upper_len - forearm_len) * 1.02
    if distance < 1e-6:
        return shoulder_torso + np.array([max_reach * 0.5, 0.0, 0.0], dtype=np.float64)
    clamped = float(np.clip(distance, min_reach, max_reach))
    return shoulder_torso + offset * (clamped / distance)


def _calibration_view_from_state(calib: _CalibrationState) -> NoitomCalibrationView:
    return NoitomCalibrationView(
        pelvis_world=calib.pelvis_world.copy(),
        body_yaw_isaac=calib.body_yaw_isaac,
        arm_length_scale=calib.arm_length_scale,
        body_height_scale=calib.body_height_scale,
    )


def _calibration_view_from_scales(
    arm_length_scale: float,
    body_height_scale: float,
    pelvis_world: np.ndarray,
    body_yaw_isaac: float = 0.0,
) -> NoitomCalibrationView:
    return NoitomCalibrationView(
        pelvis_world=pelvis_world.copy(),
        body_yaw_isaac=body_yaw_isaac,
        arm_length_scale=arm_length_scale,
        body_height_scale=body_height_scale,
    )


def _aligned_skeleton_positions(
    frame: Any,
    settings: NoitomRetargetingSettings,
    calib_view: NoitomCalibrationView | None,
) -> dict[int, np.ndarray]:
    from noitom_reference_draw import (
        ReferenceSkeletonLengths,
        aligned_reference_skeleton_from_frame,
    )

    return aligned_reference_skeleton_from_frame(
        frame,
        settings.robot_pelvis_world,
        draw_scale=1.0,
        calib_view=(None if settings.reference_use_robot_link_lengths else calib_view),
        use_robot_link_lengths=settings.reference_use_robot_link_lengths,
        link_lengths=ReferenceSkeletonLengths.from_retargeting_settings(settings),
        length_scale=settings.reference_length_scale,
        arm_length_scale=settings.reference_arm_length_scale,
        shoulder_span_scale=settings.reference_shoulder_span_scale,
    )


def _forearm_direction_from_positions(
    positions: dict[int, np.ndarray], is_left: bool
) -> np.ndarray | None:
    elbow_index = int(BodyJoint.LEFT_ELBOW if is_left else BodyJoint.RIGHT_ELBOW)
    wrist_index = int(BodyJoint.LEFT_WRIST if is_left else BodyJoint.RIGHT_WRIST)
    elbow = positions.get(elbow_index)
    wrist = positions.get(wrist_index)
    if elbow is None or wrist is None:
        return None
    forearm = wrist - elbow
    if float(np.linalg.norm(forearm)) < 1e-6:
        return None
    return _unit_direction(forearm)


def _neutral_robot_forearm_directions(
    frame: Any,
    left: _ArmCalibration,
    right: _ArmCalibration,
    settings: NoitomRetargetingSettings,
    arm_length_scale: float,
    body_height_scale: float,
    pelvis_world: np.ndarray,
) -> tuple[np.ndarray, np.ndarray] | None:
    if settings.track_aligned_mocap_wrists:
        calib_view = _calibration_view_from_scales(
            arm_length_scale,
            body_height_scale,
            pelvis_world,
        )
        positions = _aligned_skeleton_positions(frame, settings, calib_view)
        left_direction = _forearm_direction_from_positions(positions, is_left=True)
        right_direction = _forearm_direction_from_positions(positions, is_left=False)
        if left_direction is None or right_direction is None:
            return None
        return left_direction, right_direction

    return (
        _map_mocap_direction_to_robot(
            left.wrist_world - left.elbow_world,
            0.0,
            settings.operator_faces_robot,
        ),
        _map_mocap_direction_to_robot(
            right.wrist_world - right.elbow_world,
            0.0,
            settings.operator_faces_robot,
        ),
    )


def _shoulder_se3_from_aligned_positions(
    positions: dict[int, np.ndarray],
    is_left: bool,
    nominal: SE3Pose,
    settings: NoitomRetargetingSettings,
) -> SE3Pose | None:
    shoulder_index = int(
        BodyJoint.LEFT_SHOULDER if is_left else BodyJoint.RIGHT_SHOULDER
    )
    elbow_index = int(BodyJoint.LEFT_ELBOW if is_left else BodyJoint.RIGHT_ELBOW)
    shoulder = positions.get(shoulder_index)
    if shoulder is None:
        return None
    elbow = positions.get(elbow_index)
    if elbow is not None:
        upper_arm = elbow - shoulder
        quat = _elbow_quat_for_ik(
            upper_arm,
            nominal.quaternion_xyzw,
            settings,
        )
    else:
        quat = _normalize_quat(nominal.quaternion_xyzw)
    return SE3Pose(shoulder.copy(), quat)


def _elbow_quat_for_ik(
    upper_arm_dir: np.ndarray,
    nominal_quat: np.ndarray,
    settings: NoitomRetargetingSettings,
) -> np.ndarray:
    return _wrist_quat_from_forearm(
        upper_arm_dir,
        nominal_quat,
        settings.wrist_orientation_forearm_blend,
    )


def _elbow_se3_from_aligned_positions(
    positions: dict[int, np.ndarray],
    is_left: bool,
    nominal: SE3Pose,
    settings: NoitomRetargetingSettings,
) -> SE3Pose | None:
    elbow_index = int(BodyJoint.LEFT_ELBOW if is_left else BodyJoint.RIGHT_ELBOW)
    shoulder_index = int(
        BodyJoint.LEFT_SHOULDER if is_left else BodyJoint.RIGHT_SHOULDER
    )
    elbow = positions.get(elbow_index)
    if elbow is None:
        return None
    shoulder = positions.get(shoulder_index)
    if shoulder is not None:
        upper_arm = elbow - shoulder
        quat = _elbow_quat_for_ik(
            upper_arm,
            nominal.quaternion_xyzw,
            settings,
        )
    else:
        quat = _normalize_quat(nominal.quaternion_xyzw)
    return SE3Pose(elbow.copy(), quat)


def _wrist_se3_from_aligned_positions(
    positions: dict[int, np.ndarray],
    is_left: bool,
    nominal: SE3Pose,
    settings: NoitomRetargetingSettings,
    *,
    derive_orientation: bool = True,
) -> SE3Pose | None:
    wrist_index = int(BodyJoint.LEFT_WRIST if is_left else BodyJoint.RIGHT_WRIST)
    elbow_index = int(BodyJoint.LEFT_ELBOW if is_left else BodyJoint.RIGHT_ELBOW)
    wrist = positions.get(wrist_index)
    if wrist is None:
        return None
    elbow = positions.get(elbow_index)
    if derive_orientation and elbow is not None:
        forearm = wrist - elbow
        quat = _wrist_quat_for_ik(
            forearm,
            nominal.quaternion_xyzw,
            settings,
            track_orientation=False,
        )
    else:
        quat = _normalize_quat(nominal.quaternion_xyzw)
    return SE3Pose(wrist.copy(), quat)


def _nominal_shoulders_from_aligned_frame(
    frame: Any,
    settings: NoitomRetargetingSettings,
    arm_length_scale: float,
    body_height_scale: float,
    pelvis_world: np.ndarray,
) -> tuple[SE3Pose, SE3Pose] | None:
    calib_view = _calibration_view_from_scales(
        arm_length_scale, body_height_scale, pelvis_world
    )
    positions = _aligned_skeleton_positions(frame, settings, calib_view)
    if not positions:
        return None
    default_left = SE3Pose.from_nominal(
        np.zeros(3, dtype=np.float64),
        settings.nominal_left_wrist_quat_xyzw,
    )
    default_right = SE3Pose.from_nominal(
        np.zeros(3, dtype=np.float64),
        settings.nominal_right_wrist_quat_xyzw,
    )
    left = _shoulder_se3_from_aligned_positions(positions, True, default_left, settings)
    right = _shoulder_se3_from_aligned_positions(
        positions, False, default_right, settings
    )
    if left is None or right is None:
        return None
    return left, right


def _nominal_elbows_from_aligned_frame(
    frame: Any,
    settings: NoitomRetargetingSettings,
    arm_length_scale: float,
    body_height_scale: float,
    pelvis_world: np.ndarray,
) -> tuple[SE3Pose, SE3Pose] | None:
    calib_view = _calibration_view_from_scales(
        arm_length_scale, body_height_scale, pelvis_world
    )
    positions = _aligned_skeleton_positions(frame, settings, calib_view)
    if not positions:
        return None
    default_left = SE3Pose.from_nominal(
        np.zeros(3, dtype=np.float64),
        settings.nominal_left_wrist_quat_xyzw,
    )
    default_right = SE3Pose.from_nominal(
        np.zeros(3, dtype=np.float64),
        settings.nominal_right_wrist_quat_xyzw,
    )
    left = _elbow_se3_from_aligned_positions(positions, True, default_left, settings)
    right = _elbow_se3_from_aligned_positions(positions, False, default_right, settings)
    if left is None or right is None:
        return None
    return left, right


def _nominal_wrists_from_aligned_frame(
    frame: Any,
    settings: NoitomRetargetingSettings,
    arm_length_scale: float,
    body_height_scale: float,
    pelvis_world: np.ndarray,
) -> tuple[SE3Pose | None, SE3Pose | None]:
    calib_view = _calibration_view_from_scales(
        arm_length_scale, body_height_scale, pelvis_world
    )
    positions = _aligned_skeleton_positions(frame, settings, calib_view)
    if not positions:
        return None, None
    default_left = SE3Pose.from_nominal(
        settings.nominal_left_wrist_pos, settings.nominal_left_wrist_quat_xyzw
    )
    default_right = SE3Pose.from_nominal(
        settings.nominal_right_wrist_pos, settings.nominal_right_wrist_quat_xyzw
    )
    return (
        _wrist_se3_from_aligned_positions(positions, True, default_left, settings),
        _wrist_se3_from_aligned_positions(positions, False, default_right, settings),
    )


def _shoulder_target_from_aligned_skeleton(
    frame: Any,
    calib: _CalibrationState,
    settings: NoitomRetargetingSettings,
    is_left: bool,
) -> SE3Pose | None:
    calib_view = _calibration_view_from_state(calib)
    positions = _aligned_skeleton_positions(frame, settings, calib_view)
    if not positions:
        return None
    nominal = calib.nominal_left_shoulder if is_left else calib.nominal_right_shoulder
    return _shoulder_se3_from_aligned_positions(positions, is_left, nominal, settings)


def _solve_shoulder_target(
    arm: _ArmCalibration,
    neutral: _ArmCalibration,
    nominal: SE3Pose,
    settings: NoitomRetargetingSettings,
    yaw_delta: float,
    is_left: bool,
    bone_scales: _ArmBoneScales | None = None,
) -> SE3Pose:
    shoulder_robot, _elbow_robot, _wrist_robot = _arm_fk_robot_blended(
        arm, neutral, settings, yaw_delta, is_left, bone_scales=bone_scales
    )
    upper_arm = _elbow_robot - shoulder_robot
    upper_norm = float(np.linalg.norm(upper_arm))
    if upper_norm > 1e-6:
        upper_dir = upper_arm / upper_norm
    else:
        upper_dir = _map_mocap_direction_to_robot(
            arm.elbow_world - arm.shoulder_world,
            yaw_delta,
            settings.operator_faces_robot,
        )
    quat = _elbow_quat_for_ik(upper_dir, nominal.quaternion_xyzw, settings)
    return SE3Pose(shoulder_robot, quat)


def _elbow_target_from_aligned_skeleton(
    frame: Any,
    calib: _CalibrationState,
    settings: NoitomRetargetingSettings,
    is_left: bool,
) -> SE3Pose | None:
    calib_view = _calibration_view_from_state(calib)
    positions = _aligned_skeleton_positions(frame, settings, calib_view)
    if not positions:
        return None
    nominal = calib.nominal_left_elbow if is_left else calib.nominal_right_elbow
    return _elbow_se3_from_aligned_positions(positions, is_left, nominal, settings)


def _solve_elbow_target(
    arm: _ArmCalibration,
    neutral: _ArmCalibration,
    nominal: SE3Pose,
    settings: NoitomRetargetingSettings,
    yaw_delta: float,
    is_left: bool,
    bone_scales: _ArmBoneScales | None = None,
) -> SE3Pose:
    _shoulder_robot, elbow_robot, _wrist_robot = _arm_fk_robot_blended(
        arm, neutral, settings, yaw_delta, is_left, bone_scales=bone_scales
    )
    upper_arm = elbow_robot - _shoulder_world_robot(settings, yaw_delta, is_left)
    upper_norm = float(np.linalg.norm(upper_arm))
    if upper_norm > 1e-6:
        upper_dir = upper_arm / upper_norm
    else:
        upper_dir = _map_mocap_direction_to_robot(
            arm.elbow_world - arm.shoulder_world,
            yaw_delta,
            settings.operator_faces_robot,
        )
    quat = _elbow_quat_for_ik(upper_dir, nominal.quaternion_xyzw, settings)
    return SE3Pose(elbow_robot, quat)


def _wrist_target_from_aligned_skeleton(
    frame: Any,
    calib: _CalibrationState,
    settings: NoitomRetargetingSettings,
    is_left: bool,
) -> SE3Pose | None:
    calib_view = _calibration_view_from_state(calib)
    positions = _aligned_skeleton_positions(frame, settings, calib_view)
    if not positions:
        return None
    nominal = calib.nominal_left if is_left else calib.nominal_right
    return _wrist_se3_from_aligned_positions(
        positions,
        is_left,
        nominal,
        settings,
        derive_orientation=False,
    )


def _aligned_forearm_direction(
    frame: Any,
    calib: _CalibrationState,
    settings: NoitomRetargetingSettings,
    is_left: bool,
) -> np.ndarray:
    positions = _aligned_skeleton_positions(
        frame, settings, _calibration_view_from_state(calib)
    )
    direction = _forearm_direction_from_positions(positions, is_left)
    if direction is None:
        return np.array([0.0, 1.0, 0.0], dtype=np.float64)
    return direction


def _solve_wrist_target(
    torso: _TorsoFrame,
    arm: _ArmCalibration,
    pelvis_world: np.ndarray,
    neutral: _ArmCalibration,
    neutral_torso: _TorsoFrame,
    nominal: SE3Pose,
    neutral_forearm_robot: np.ndarray,
    calib_yaw: float,
    arm_length_scale: float,
    settings: NoitomRetargetingSettings,
    is_left: bool,
    bounded_twist_rad: float | None = None,
    bone_scales: _ArmBoneScales | None = None,
) -> SE3Pose:
    """Compute one wrist IK target from a mocap frame."""
    yaw_delta = _resolve_yaw_delta(_compute_torso_yaw(torso) - calib_yaw, settings)

    if settings.use_posture_based_arms:
        shoulder_robot, elbow_robot, wrist_robot = _arm_fk_robot_blended(
            arm, neutral, settings, yaw_delta, is_left, bone_scales=bone_scales
        )
        forearm = wrist_robot - elbow_robot
        forearm_norm = float(np.linalg.norm(forearm))
        if forearm_norm > 1e-6:
            forearm_dir = forearm / forearm_norm
        else:
            forearm_dir = _map_mocap_direction_to_robot(
                arm.wrist_world - arm.elbow_world,
                yaw_delta,
                settings.operator_faces_robot,
            )
        quat = _tracked_wrist_quaternion(
            torso,
            arm,
            neutral_torso,
            neutral,
            nominal.quaternion_xyzw,
            neutral_forearm_robot,
            forearm_dir,
            settings,
            bounded_twist_rad=bounded_twist_rad,
        )
        return SE3Pose(wrist_robot, quat)

    # Non-posture path: scale raw mocap position into robot frame.
    rel_now = arm.wrist_world - pelvis_world
    anchor = settings.robot_pelvis_world.astype(np.float64)
    off_shoulder = _shoulder_offset_robot(settings, yaw_delta, is_left)
    off_wrist = _map_mocap_rel_to_robot_offset(
        rel_now,
        arm_length_scale,
        settings.motion_scale,
        yaw_delta,
        settings.operator_faces_robot,
    )
    if bone_scales is not None:
        upper_len = bone_scales.upper_arm
        forearm_len = bone_scales.forearm
    else:
        upper_len = settings.robot_upper_arm_length
        forearm_len = settings.robot_forearm_length
    clamped = _clamp_reach(off_shoulder, off_wrist, upper_len, forearm_len)
    target_pos = anchor + clamped

    forearm_dir = _map_mocap_direction_to_robot(
        arm.wrist_world - arm.elbow_world,
        yaw_delta,
        settings.operator_faces_robot,
    )
    quat = _tracked_wrist_quaternion(
        torso,
        arm,
        neutral_torso,
        neutral,
        nominal.quaternion_xyzw,
        neutral_forearm_robot,
        forearm_dir,
        settings,
        bounded_twist_rad=bounded_twist_rad,
    )

    return SE3Pose(target_pos, quat)


def _smooth_pose(
    current: SE3Pose,
    target: SE3Pose,
    position_alpha: float,
    rotation_alpha: float,
) -> SE3Pose:
    pos_alpha = float(np.clip(position_alpha, 0.0, 1.0))
    rot_alpha = float(np.clip(rotation_alpha, 0.0, 1.0))
    position = (1.0 - pos_alpha) * current.position + pos_alpha * target.position
    if rot_alpha <= 0.0:
        quaternion = current.quaternion_xyzw.copy()
    elif rot_alpha >= 1.0:
        quaternion = target.quaternion_xyzw.copy()
    else:
        slerp = Slerp(
            [0.0, 1.0],
            Rotation.from_quat(
                np.vstack([current.quaternion_xyzw, target.quaternion_xyzw])
            ),
        )
        quaternion = _normalize_quat(slerp([rot_alpha]).as_quat()[0])
    return SE3Pose(position, quaternion)


__all__ = [
    "ArmIkTargets",
    "DEFAULT_NOITOM_IK_CONFIG_PATH",
    "NoitomArmIkTargetNode",
    "NoitomCalibrationView",
    "NoitomG1Retargeter",
    "NoitomIkConfig",
    "NoitomIkMatch",
    "NoitomPinkTaskWeights",
    "NoitomRetargetingSettings",
    "WristOrientationDiagnostics",
    "WristPoseDiagnostics",
    "SE3Pose",
    "compute_robot_reference_positions",
    "load_noitom_ik_config",
    "map_point_to_robot_frame",
    "noitom_position_to_isaac",
    "noitom_quaternion_to_isaac",
]
