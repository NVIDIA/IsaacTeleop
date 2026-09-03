# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""External Isaac Lab task registration for Noitom-driven G1 teleop testing."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium.envs.registration import registry
from scipy.spatial.transform import Rotation

from isaaclab.utils.configclass import configclass
from isaaclab_tasks.manager_based.locomanipulation.pick_place.locomanipulation_g1_env_cfg import (
    LocomanipulationG1EnvCfg,
)
from isaacteleop.schema import (
    BodyJoint,
    FullBodyPose,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    DeviceIOFullBodyPoseTracked,
    IDeviceIOSource,
)
from isaacteleop.retargeting_engine.interface import (
    ComputeContext,
    OutputCombiner,
    RetargeterIO,
    RetargeterIOType,
    TensorGroup,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import DLDataType, NDArrayType
from isaacteleop.teleop_session_manager import PluginConfig

from noitom_retargeting import (
    ArmIkTargets,
    DEFAULT_NOITOM_IK_CONFIG_PATH,
    NoitomG1Retargeter,
    NoitomRetargetingSettings,
    load_noitom_ik_config,
    noitom_position_to_isaac,
)
from noitom_reference_draw import (
    ReferenceSkeletonLengths,
    aligned_reference_skeleton_from_frame,
)

TASK_ID = "Isaac-PickPlace-Locomanipulation-G1-Noitom-Abs-v0"

_FULL_BODY_INPUT = "deviceio_full_body"
_ACTION_OUTPUT = "action"
_G1_ACTION_DIM_WRIST_TORSO = 35
_G1_ACTION_DIM_WITH_ARM_IK = 63
_PINK_PELVIS_LINK = "g1_29dof_with_hand_rev_1_0_pelvis"
_PINK_TORSO_LINK = "torso_link"
_PINK_LEFT_ELBOW_LINK = "g1_29dof_with_hand_rev_1_0_left_elbow_link"
_PINK_RIGHT_ELBOW_LINK = "g1_29dof_with_hand_rev_1_0_right_elbow_link"
_PINK_LEFT_SHOULDER_LINK = "g1_29dof_with_hand_rev_1_0_left_shoulder_pitch_link"
_PINK_RIGHT_SHOULDER_LINK = "g1_29dof_with_hand_rev_1_0_right_shoulder_pitch_link"
_LineList = list[list[float]]
_ColorList = list[tuple[float, float, float, float]]

_NOITOM_REFERENCE_COLOR = (0.15, 0.85, 1.0, 1.0)
_NOITOM_REFERENCE_LINE_THICKNESS = 4.0
_NOITOM_REFERENCE_JOINT_MARKER_SIZE = 0.018
# Approximate G1 pelvis height in the locomanipulation scene (meters, Isaac Z-up).
_ROBOT_PELVIS_ANCHOR = (0.0, 0.0, 0.72)
_NOITOM_REFERENCE_DEFAULT_OFFSET = (0.0, 0.0, 0.0)
_NOITOM_WRIST_TARGET_COLOR = (1.0, 0.65, 0.1, 1.0)
_NOITOM_WRIST_TARGET_MARKER_SIZE = 0.025
_NOITOM_ELBOW_TARGET_COLOR = (1.0, 0.2, 0.85, 1.0)
_NOITOM_ELBOW_TARGET_MARKER_SIZE = 0.022
_NOITOM_SHOULDER_TARGET_COLOR = (0.2, 1.0, 0.35, 1.0)
_NOITOM_SHOULDER_TARGET_MARKER_SIZE = 0.02
_FRAME_AXIS_COLORS = (
    (1.0, 0.1, 0.1, 1.0),
    (0.1, 1.0, 0.1, 1.0),
    (0.1, 0.35, 1.0, 1.0),
)
_NOITOM_PLUGIN_NAME = "noitom_mocap"
_NOITOM_PLUGIN_ROOT_ID = "noitom_mocap"
_NOITOM_VENDOR_ID = "body.noitom"


def g1_action_dim(*, use_arm_ik_frame_tasks: bool) -> int:
    """Flat teleop action size for the Noitom G1 locomanipulation task."""
    return (
        _G1_ACTION_DIM_WITH_ARM_IK
        if use_arm_ik_frame_tasks
        else _G1_ACTION_DIM_WRIST_TORSO
    )


@dataclass(frozen=True)
class NoitomG1Settings:
    """Release defaults for the Noitom-driven G1 locomanipulation example."""

    collection_id: str = "noitom_mocap"
    max_flatbuffer_size: int = 16 * 1024
    plugin_auto_launch: bool = True
    teleoperation_active_default: bool = True
    enable_motion: bool = True
    print_period_s: float = 0.5
    orientation_debug: bool = False
    clear_workspace: bool = False
    robot_world_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    draw_reference: bool = True
    draw_scale: float = 1.0
    draw_offset: tuple[float, float, float] = _NOITOM_REFERENCE_DEFAULT_OFFSET
    # Anchor the cyan skeleton to the robot pelvis instead of a fixed world offset.
    draw_pelvis_relative: bool = True
    draw_pelvis_anchor: tuple[float, float, float] = _ROBOT_PELVIS_ANCHOR
    draw_wrist_targets: bool = True
    draw_wrist_frames: bool = False
    wrist_frame_axis_length: float = 0.10
    draw_elbow_targets: bool = True
    draw_shoulder_targets: bool = True
    # Wrist + torso + elbow + shoulder LocalFrameTasks for Pink IK (63D action).
    use_arm_ik_frame_tasks: bool = True
    # Noitom-only Pink tuning for fast recorded motion.
    pink_task_gain: float = 0.20
    pink_lm_damping: float = 50.0
    # Symmetric safety bounds applied inside Noitom Pink and to its output only.
    wrist_pitch_limit_deg: float = 80.0
    wrist_yaw_limit_deg: float = 80.0
    retargeting: NoitomRetargetingSettings = field(
        default_factory=lambda: NoitomRetargetingSettings(
            robot_pelvis_world=np.array(_ROBOT_PELVIS_ANCHOR, dtype=np.float64),
            motion_scale=1.0,
            track_aligned_mocap_wrists=True,
            wrist_orientation_mode="source",
            wrist_twist_limit_deg=60.0,
            track_elbow_ik_targets=True,
            track_shoulder_ik_targets=True,
            ik_config_path=str(DEFAULT_NOITOM_IK_CONFIG_PATH),
        )
    )


_FULL_BODY_BONES = (
    (BodyJoint.PELVIS, BodyJoint.SPINE1),
    (BodyJoint.SPINE1, BodyJoint.SPINE2),
    (BodyJoint.SPINE2, BodyJoint.SPINE3),
    (BodyJoint.SPINE3, BodyJoint.NECK),
    (BodyJoint.NECK, BodyJoint.HEAD),
    (BodyJoint.SPINE3, BodyJoint.LEFT_COLLAR),
    (BodyJoint.LEFT_COLLAR, BodyJoint.LEFT_SHOULDER),
    (BodyJoint.LEFT_SHOULDER, BodyJoint.LEFT_ELBOW),
    (BodyJoint.LEFT_ELBOW, BodyJoint.LEFT_WRIST),
    (BodyJoint.LEFT_WRIST, BodyJoint.LEFT_HAND),
    (BodyJoint.SPINE3, BodyJoint.RIGHT_COLLAR),
    (BodyJoint.RIGHT_COLLAR, BodyJoint.RIGHT_SHOULDER),
    (BodyJoint.RIGHT_SHOULDER, BodyJoint.RIGHT_ELBOW),
    (BodyJoint.RIGHT_ELBOW, BodyJoint.RIGHT_WRIST),
    (BodyJoint.RIGHT_WRIST, BodyJoint.RIGHT_HAND),
    (BodyJoint.PELVIS, BodyJoint.LEFT_HIP),
    (BodyJoint.LEFT_HIP, BodyJoint.LEFT_KNEE),
    (BodyJoint.LEFT_KNEE, BodyJoint.LEFT_ANKLE),
    (BodyJoint.LEFT_ANKLE, BodyJoint.LEFT_FOOT),
    (BodyJoint.PELVIS, BodyJoint.RIGHT_HIP),
    (BodyJoint.RIGHT_HIP, BodyJoint.RIGHT_KNEE),
    (BodyJoint.RIGHT_KNEE, BodyJoint.RIGHT_ANKLE),
    (BodyJoint.RIGHT_ANKLE, BodyJoint.RIGHT_FOOT),
)
DEFAULT_NOITOM_G1_SETTINGS = NoitomG1Settings()


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None else float(value)


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower()


def _env_vec3(
    name: str, default: tuple[float, float, float]
) -> tuple[float, float, float]:
    value = os.environ.get(name)
    if value is None:
        return default
    parts = value.split(",")
    if len(parts) != 3:
        raise ValueError(f"{name} must contain three comma-separated numbers")
    return tuple(float(part.strip()) for part in parts)


def _noitom_settings_from_env() -> NoitomG1Settings:
    defaults = DEFAULT_NOITOM_G1_SETTINGS
    robot_world_offset = _env_vec3("NOITOM_ROBOT_OFFSET", defaults.robot_world_offset)
    offset = np.asarray(robot_world_offset, dtype=np.float64)
    draw_pelvis_anchor = tuple(
        np.asarray(defaults.draw_pelvis_anchor, dtype=np.float64) + offset
    )
    retargeting = replace(
        defaults.retargeting,
        robot_pelvis_world=defaults.retargeting.robot_pelvis_world + offset,
        wrist_orientation_mode=_env_str(
            "NOITOM_WRIST_ORIENTATION_MODE",
            defaults.retargeting.wrist_orientation_mode,
        ),
        wrist_twist_limit_deg=_env_float(
            "NOITOM_WRIST_TWIST_LIMIT_DEG",
            defaults.retargeting.wrist_twist_limit_deg,
        ),
        wrist_twist_max_step_deg=_env_float(
            "NOITOM_WRIST_TWIST_MAX_STEP_DEG",
            defaults.retargeting.wrist_twist_max_step_deg,
        ),
        torso_orientation_scale=_env_float(
            "NOITOM_TORSO_ORIENTATION_SCALE",
            defaults.retargeting.torso_orientation_scale,
        ),
        torso_rotation_smoothing=_env_float(
            "NOITOM_TORSO_ROTATION_SMOOTHING",
            defaults.retargeting.torso_rotation_smoothing,
        ),
        torso_yaw_limit_deg=_env_float(
            "NOITOM_TORSO_YAW_LIMIT_DEG",
            defaults.retargeting.torso_yaw_limit_deg,
        ),
        torso_roll_limit_deg=_env_float(
            "NOITOM_TORSO_ROLL_LIMIT_DEG",
            defaults.retargeting.torso_roll_limit_deg,
        ),
        torso_pitch_limit_deg=_env_float(
            "NOITOM_TORSO_PITCH_LIMIT_DEG",
            defaults.retargeting.torso_pitch_limit_deg,
        ),
        ik_config_path=os.environ.get(
            "NOITOM_IK_CONFIG", defaults.retargeting.ik_config_path
        ),
    )
    return replace(
        defaults,
        plugin_auto_launch=_env_bool(
            "NOITOM_MOCAP_AUTO_LAUNCH",
            defaults.plugin_auto_launch,
        ),
        orientation_debug=_env_bool(
            "NOITOM_ORIENTATION_DEBUG", defaults.orientation_debug
        ),
        clear_workspace=_env_bool("NOITOM_CLEAR_WORKSPACE", defaults.clear_workspace),
        draw_wrist_frames=_env_bool(
            "NOITOM_DRAW_WRIST_FRAMES", defaults.draw_wrist_frames
        ),
        pink_task_gain=_env_float("NOITOM_PINK_TASK_GAIN", defaults.pink_task_gain),
        pink_lm_damping=_env_float("NOITOM_PINK_LM_DAMPING", defaults.pink_lm_damping),
        wrist_pitch_limit_deg=_env_float(
            "NOITOM_WRIST_PITCH_LIMIT_DEG", defaults.wrist_pitch_limit_deg
        ),
        wrist_yaw_limit_deg=_env_float(
            "NOITOM_WRIST_YAW_LIMIT_DEG", defaults.wrist_yaw_limit_deg
        ),
        robot_world_offset=robot_world_offset,
        draw_pelvis_anchor=draw_pelvis_anchor,
        retargeting=retargeting,
    )


def _plugin_search_paths() -> list[Path]:
    base = Path(__file__).resolve().parents[2]
    candidates = [
        base / "plugins",
        base / "install" / "plugins",
    ]
    return [path for path in candidates if path.exists()]


def _noitom_plugin_configs(settings: NoitomG1Settings) -> list[PluginConfig]:
    if not settings.plugin_auto_launch:
        return []
    search_paths = _plugin_search_paths()
    if not search_paths:
        raise RuntimeError(
            "Noitom plugin directory not found. Run `cmake --install build` "
            "or set NOITOM_MOCAP_AUTO_LAUNCH=0 for a manually started plugin."
        )
    return [
        # Noitom plugin launch arguments live in src/plugins/noitom_mocap/plugin.yaml.
        PluginConfig(
            plugin_name=_NOITOM_PLUGIN_NAME,
            plugin_root_id=_NOITOM_PLUGIN_ROOT_ID,
            search_paths=search_paths,
        )
    ]


# Waist joints stay in IK; clip targets slightly inside URDF hard stops (not fixed narrow ranges).
_WAIST_JOINT_NAMES = frozenset(
    {"waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint"}
)
# Inset from hard joint limits (rad). Small enough to avoid IK deadlock at the stops.
_WAIST_HARD_LIMIT_MARGIN_RAD = 0.10
_WRIST_HARD_LIMIT_MARGIN_RAD = 0.05


def _normalized_pose_xyzw(pose: np.ndarray) -> np.ndarray:
    """Return a copied 7DoF pose with a normalized xyzw quaternion."""
    result = np.asarray(pose, dtype=np.float64).copy()
    if result.shape != (7,):
        raise ValueError(f"expected a 7DoF pose, got shape {result.shape}")
    norm = float(np.linalg.norm(result[3:7]))
    if norm < 1.0e-8:
        raise ValueError("pose quaternion must be nonzero")
    result[3:7] /= norm
    return result


def _pose_error(left: np.ndarray, right: np.ndarray) -> tuple[float, float]:
    """Return position meters and sign-invariant quaternion distance degrees."""
    left_pose = _normalized_pose_xyzw(left)
    right_pose = _normalized_pose_xyzw(right)
    return (
        float(np.linalg.norm(left_pose[:3] - right_pose[:3])),
        _quaternion_distance_deg(left_pose[3:7], right_pose[3:7]),
    )


def _pose_to_matrix(pose: np.ndarray) -> np.ndarray:
    normalized = _normalized_pose_xyzw(pose)
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = _quaternion_matrix(normalized[3:7])
    transform[:3, 3] = normalized[:3]
    return transform


def _matrix_to_pose(matrix: np.ndarray) -> np.ndarray:
    transform = np.asarray(matrix, dtype=np.float64)
    if transform.shape != (4, 4):
        raise ValueError(f"expected a 4x4 transform, got shape {transform.shape}")
    quaternion = Rotation.from_matrix(transform[:3, :3]).as_quat()
    return _normalized_pose_xyzw(np.concatenate([transform[:3, 3], quaternion]))


def _pose_in_local_frame(
    world_pose: np.ndarray, local_frame_world: np.ndarray
) -> np.ndarray:
    """Express one environment-world pose in a supplied local-frame transform."""
    local_from_world = np.linalg.inv(np.asarray(local_frame_world, dtype=np.float64))
    return _matrix_to_pose(local_from_world @ _pose_to_matrix(world_pose))


def _pose_from_local_frame(
    local_pose: np.ndarray, local_frame_world: np.ndarray
) -> np.ndarray:
    """Compose one local pose into environment world using the supplied transform."""
    return _matrix_to_pose(
        np.asarray(local_frame_world, dtype=np.float64) @ _pose_to_matrix(local_pose)
    )


def _environment_world_pose(
    simulator_world_pose: np.ndarray, env_origin: np.ndarray
) -> np.ndarray:
    """Subtract an Isaac environment origin while preserving link orientation."""
    pose = _normalized_pose_xyzw(simulator_world_pose)
    pose[:3] -= np.asarray(env_origin, dtype=np.float64)
    return pose


def _pin_se3_pose(transform: Any) -> np.ndarray:
    """Convert a Pinocchio-style SE3 into a normalized xyzw 7DoF pose."""
    return _normalized_pose_xyzw(
        np.concatenate(
            [
                np.asarray(transform.translation, dtype=np.float64),
                Rotation.from_matrix(
                    np.asarray(transform.rotation, dtype=np.float64)
                ).as_quat(),
            ]
        )
    )


def _pink_solution_fk_pelvis_poses(
    ik_controller: Any,
    current_joint_positions_isaac: np.ndarray,
    controlled_joint_ids: list[int],
    final_solution: np.ndarray,
    wrist_frame_names: dict[str, str],
) -> dict[str, np.ndarray]:
    """Evaluate final clipped joint targets without mutating Pink's solve state."""
    configuration = ik_controller.pink_configuration
    saved_configuration = np.asarray(configuration.full_q, dtype=np.float64).copy()
    solved_configuration = np.asarray(
        current_joint_positions_isaac, dtype=np.float64
    ).copy()
    solved_configuration[np.asarray(controlled_joint_ids, dtype=np.int64)] = np.asarray(
        final_solution, dtype=np.float64
    )
    pink_ordered = solved_configuration[ik_controller.isaac_lab_to_pink_ordering]
    try:
        configuration.update(pink_ordered)
        return {
            side: _pin_se3_pose(
                configuration.get_transform(frame_name, _PINK_PELVIS_LINK)
            )
            for side, frame_name in wrist_frame_names.items()
        }
    finally:
        # Diagnostics must never leave FK state behind for the next control solve.
        configuration.update(saved_configuration)


def _build_noitom_pink_ik_action_class(
    orientation_debug: bool,
    print_period_s: float,
    draw_wrist_frames: bool,
    wrist_frame_axis_length: float,
    wrist_pitch_limit_deg: float,
    wrist_yaw_limit_deg: float,
):
    """Lazy import so unit tests can load noitom_tasks without Isaac Lab."""
    import torch
    from isaaclab.controllers.pink_ik.pink_tasks import LocalFrameTask
    from isaaclab.envs.mdp.actions.pink_task_space_actions import (
        PinkInverseKinematicsAction,
    )

    class NoitomPinkInverseKinematicsAction(PinkInverseKinematicsAction):
        """Pink IK with Noitom-only waist and wrist safety limits."""

        def __init__(self, cfg, env):
            super().__init__(cfg, env)
            self._orientation_debug = orientation_debug
            self._orientation_debug_period_s = max(0.0, print_period_s)
            self._last_orientation_debug_s = 0.0
            self._wrist_body_ids: dict[str, int] = {}
            self._wrist_joint_debug: dict[
                str, list[tuple[str, int, int, float, float]]
            ] = {"left": [], "right": []}
            self._last_ik_current = None
            self._last_ik_solution = None
            self._solve_cycle = 0
            self._pink_input_world = None
            self._pink_target_pelvis: list[dict[str, np.ndarray]] | None = None
            self._wrist_pink_frame_names: dict[str, str] = {}
            self._wrist_pink_tasks: list[dict[str, Any]] = []
            self._g1_wrist_frame_viz = None
            for side in ("left", "right"):
                suffix = f"_{side}_wrist_yaw_link"
                matches = [
                    task.frame
                    for task in self._ik_controllers[0].cfg.variable_input_tasks
                    if isinstance(task, LocalFrameTask) and task.frame.endswith(suffix)
                ]
                if len(matches) != 1:
                    raise RuntimeError(
                        f"Expected one Pink {side} wrist frame, found {matches}"
                    )
                self._wrist_pink_frame_names[side] = matches[0]
            for ik_controller in self._ik_controllers:
                tasks_by_frame = {
                    task.frame: task
                    for task in ik_controller.cfg.variable_input_tasks
                    if isinstance(task, LocalFrameTask)
                }
                self._wrist_pink_tasks.append(
                    {
                        side: tasks_by_frame[frame_name]
                        for side, frame_name in self._wrist_pink_frame_names.items()
                    }
                )
            if self._orientation_debug or draw_wrist_frames:
                for side in ("left", "right"):
                    body_name = self.cfg.target_eef_link_names[f"{side}_wrist"]
                    body_ids, _body_names = self._asset.find_bodies([body_name])
                    if len(body_ids) != 1:
                        raise RuntimeError(
                            f"Expected one G1 {side} wrist body for {body_name}, "
                            f"found {len(body_ids)}"
                        )
                    self._wrist_body_ids[side] = body_ids[0]
            if draw_wrist_frames:
                from isaaclab.markers import VisualizationMarkers
                from isaaclab.markers.config import FRAME_MARKER_CFG

                marker_cfg = FRAME_MARKER_CFG.copy()
                marker_cfg.prim_path = "/Visuals/Noitom/G1WristFrames"
                axis_length = max(0.01, wrist_frame_axis_length)
                marker_cfg.markers["frame"].scale = (
                    axis_length,
                    axis_length,
                    axis_length,
                )
                self._g1_wrist_frame_viz = VisualizationMarkers(marker_cfg)
                print(
                    "NoitomG1Env: drawing actual G1 wrist frames "
                    "(X=red, Y=green, Z=blue)"
                )
            if wrist_pitch_limit_deg <= 0.0 or wrist_yaw_limit_deg <= 0.0:
                raise ValueError("Noitom wrist pitch/yaw limits must be positive")

            clip_ids: list[int] = []
            lows: list[float] = []
            highs: list[float] = []
            safe_bounds: dict[str, tuple[float, float]] = {}
            hard_limits = self._asset.data.joint_pos_limits.torch[0]
            name_to_joint_idx = {
                name: index for index, name in enumerate(self._asset.data.joint_names)
            }
            wrist_limits_rad = {
                "pitch": float(np.deg2rad(wrist_pitch_limit_deg)),
                "yaw": float(np.deg2rad(wrist_yaw_limit_deg)),
            }
            for ik_index, name in enumerate(self._isaaclab_controlled_joint_names):
                joint_idx = name_to_joint_idx[name]
                lo_hard = float(hard_limits[joint_idx, 0])
                hi_hard = float(hard_limits[joint_idx, 1])
                if name in _WAIST_JOINT_NAMES:
                    lo = lo_hard + _WAIST_HARD_LIMIT_MARGIN_RAD
                    hi = hi_hard - _WAIST_HARD_LIMIT_MARGIN_RAD
                elif name.endswith("_wrist_pitch_joint"):
                    limit = wrist_limits_rad["pitch"]
                    lo = max(lo_hard + _WRIST_HARD_LIMIT_MARGIN_RAD, -limit)
                    hi = min(hi_hard - _WRIST_HARD_LIMIT_MARGIN_RAD, limit)
                elif name.endswith("_wrist_yaw_joint"):
                    limit = wrist_limits_rad["yaw"]
                    lo = max(lo_hard + _WRIST_HARD_LIMIT_MARGIN_RAD, -limit)
                    hi = min(hi_hard - _WRIST_HARD_LIMIT_MARGIN_RAD, limit)
                else:
                    continue
                if lo >= hi:
                    mid = 0.5 * (lo_hard + hi_hard)
                    half = 0.45 * (hi_hard - lo_hard)
                    lo, hi = mid - half, mid + half
                safe_bounds[name] = (lo, hi)
                clip_ids.append(ik_index)
                lows.append(lo)
                highs.append(hi)
            self._safe_ik_indices = clip_ids
            if clip_ids:
                self._safe_low = torch.tensor(lows, device=self.device).view(1, -1)
                self._safe_high = torch.tensor(highs, device=self.device).view(1, -1)
                self._safe_ik_idx = torch.tensor(
                    clip_ids, device=self.device, dtype=torch.long
                )

            # Pink reads these model limits when it builds each QP. Restrict only
            # this Noitom action's controller models; generic Isaac Lab tasks keep
            # their original URDF limits.
            wrist_bounds = {
                name: bounds
                for name, bounds in safe_bounds.items()
                if "_wrist_pitch_joint" in name or "_wrist_yaw_joint" in name
            }
            for ik_controller in self._ik_controllers:
                model = ik_controller.pink_configuration.model
                for name, (lo, hi) in wrist_bounds.items():
                    joint_id = model.getJointId(name)
                    if joint_id <= 0 or joint_id >= model.njoints:
                        raise RuntimeError(f"Pink model does not contain {name}")
                    joint = model.joints[joint_id]
                    if joint.nq != 1:
                        raise RuntimeError(f"Expected one-DoF wrist joint {name}")
                    model.lowerPositionLimit[joint.idx_q] = lo
                    model.upperPositionLimit[joint.idx_q] = hi

            for side in ("left", "right"):
                for axis in ("roll", "pitch", "yaw"):
                    name = f"{side}_wrist_{axis}_joint"
                    if name not in self._isaaclab_controlled_joint_names:
                        continue
                    ik_index = self._isaaclab_controlled_joint_names.index(name)
                    joint_idx = name_to_joint_idx[name]
                    lo_hard = float(hard_limits[joint_idx, 0])
                    hi_hard = float(hard_limits[joint_idx, 1])
                    lo, hi = safe_bounds.get(name, (lo_hard, hi_hard))
                    self._wrist_joint_debug[side].append(
                        (axis, ik_index, joint_idx, lo, hi)
                    )
            print(
                "NoitomG1Env: Noitom-only wrist IK limits "
                f"pitch=+/-{wrist_pitch_limit_deg:.1f} deg "
                f"yaw=+/-{wrist_yaw_limit_deg:.1f} deg"
            )

        def _compute_ik_solutions(self) -> torch.Tensor:
            current_all = self._asset.data.joint_pos.torch.clone()
            current = self._asset.data.joint_pos.torch[
                :, self._isaaclab_controlled_joint_ids
            ].clone()
            sol = super()._compute_ik_solutions()
            if self._safe_ik_indices:
                safe_joints = sol.index_select(1, self._safe_ik_idx)
                sol.index_copy_(
                    1,
                    self._safe_ik_idx,
                    torch.clamp(safe_joints, self._safe_low, self._safe_high),
                )
            self._last_ik_current = current
            self._last_ik_solution = sol.detach().clone()
            self._maybe_print_pink_pose_diagnostics(current_all, current, sol)
            return sol

        def process_actions(self, actions: torch.Tensor) -> None:
            super().process_actions(actions)
            if self._orientation_debug:
                self._solve_cycle += 1
                self._pink_input_world = actions[:, :14].detach().clone()
                self._pink_target_pelvis = []
                for wrist_tasks in self._wrist_pink_tasks:
                    self._pink_target_pelvis.append(
                        {
                            side: _pin_se3_pose(task.transform_target_to_base)
                            for side, task in wrist_tasks.items()
                        }
                    )
            body_poses = self._asset.data.body_link_pose_w.torch
            if self._g1_wrist_frame_viz is not None:
                actual_poses = torch.stack(
                    [
                        body_poses[0, self._wrist_body_ids["left"]],
                        body_poses[0, self._wrist_body_ids["right"]],
                    ]
                )
                self._g1_wrist_frame_viz.visualize(
                    actual_poses[:, :3], actual_poses[:, 3:7]
                )

        def _maybe_print_pink_pose_diagnostics(
            self,
            current_all: torch.Tensor,
            current_controlled: torch.Tensor,
            solution: torch.Tensor,
        ) -> None:
            if not self._orientation_debug:
                return
            if self._pink_input_world is None or self._pink_target_pelvis is None:
                return
            now_s = time.monotonic()
            if (
                self._orientation_debug_period_s > 0.0
                and now_s - self._last_orientation_debug_s
                < self._orientation_debug_period_s
            ):
                return
            self._last_orientation_debug_s = now_s
            body_poses = self._asset.data.body_link_pose_w.torch
            env_origins = self._env.scene.env_origins
            for env_index, ik_controller in enumerate(self._ik_controllers):
                base_world = (
                    self.base_link_frame_in_world_rf[env_index].detach().cpu().numpy()
                )
                solution_fk_pelvis = _pink_solution_fk_pelvis_poses(
                    ik_controller,
                    current_all[env_index].detach().cpu().numpy(),
                    self._isaaclab_controlled_joint_ids,
                    solution[env_index].detach().cpu().numpy(),
                    self._wrist_pink_frame_names,
                )
                env_label = f" env={env_index}" if self.num_envs > 1 else ""
                for side, action_start in (("left", 0), ("right", 7)):
                    input_world = _normalized_pose_xyzw(
                        self._pink_input_world[
                            env_index, action_start : action_start + 7
                        ]
                        .detach()
                        .cpu()
                        .numpy()
                    )
                    target_pelvis = self._pink_target_pelvis[env_index][side]
                    solution_pelvis = solution_fk_pelvis[side]
                    solution_world = _pose_from_local_frame(solution_pelvis, base_world)
                    actual_world = _environment_world_pose(
                        body_poses[env_index, self._wrist_body_ids[side]]
                        .detach()
                        .cpu()
                        .numpy(),
                        env_origins[env_index].detach().cpu().numpy(),
                    )
                    actual_pelvis = _pose_in_local_frame(actual_world, base_world)
                    input_solution = _pose_error(input_world, solution_world)
                    solution_actual = _pose_error(solution_world, actual_world)
                    input_actual = _pose_error(input_world, actual_world)

                    for stage, pose in (
                        ("pink_input_world", input_world),
                        ("pink_target_pelvis", target_pelvis),
                        ("pink_solution_fk_world", solution_world),
                        ("pink_solution_fk_pelvis", solution_pelvis),
                        ("robot_actual_pre_apply_world", actual_world),
                        ("robot_actual_pelvis", actual_pelvis),
                    ):
                        print(
                            f"NoitomWristPoseDebug solve_cycle={self._solve_cycle}"
                            f"{env_label} stage={stage} side={side} "
                            f"{_fmt_pose_debug(pose)}"
                        )
                    print(
                        f"NoitomWristPoseError solve_cycle={self._solve_cycle}"
                        f"{env_label} side={side} "
                        f"input_to_solution_pos_m={input_solution[0]:.6f} "
                        f"input_to_solution_rot_deg={input_solution[1]:.6f} "
                        f"solution_to_actual_pos_m={solution_actual[0]:.6f} "
                        f"solution_to_actual_rot_deg={solution_actual[1]:.6f} "
                        f"input_to_actual_pos_m={input_actual[0]:.6f} "
                        f"input_to_actual_rot_deg={input_actual[1]:.6f}"
                    )
                    print(
                        f"NoitomPinkOrientationDebug side={side} "
                        f"target_q={_fmt_array(input_world[3:7], precision=6)} "
                        f"actual_q={_fmt_array(actual_world[3:7], precision=6)} "
                        f"error_deg={input_actual[1]:.2f}"
                    )
                    joint_info = self._wrist_joint_debug[side]
                    if not joint_info:
                        continue
                    actual_joints = torch.stack(
                        [
                            self._asset.data.joint_pos.torch[env_index, joint_idx]
                            for _axis, _ik_idx, joint_idx, _lo, _hi in joint_info
                        ]
                    )
                    ik_targets = torch.stack(
                        [
                            solution[env_index, ik_idx]
                            for _axis, ik_idx, _joint_idx, _lo, _hi in joint_info
                        ]
                    )
                    previous = torch.stack(
                        [
                            current_controlled[env_index, ik_idx]
                            for _axis, ik_idx, _joint_idx, _lo, _hi in joint_info
                        ]
                    )
                    lows = torch.tensor(
                        [lo for _axis, _ik_idx, _joint_idx, lo, _hi in joint_info],
                        device=self.device,
                    )
                    highs = torch.tensor(
                        [hi for _axis, _ik_idx, _joint_idx, _lo, hi in joint_info],
                        device=self.device,
                    )
                    margins = torch.minimum(actual_joints - lows, highs - actual_joints)
                    ik_step_max_rad = float(
                        torch.max(torch.abs(ik_targets - previous)).item()
                    )
                    solver_held = ik_step_max_rad < 1.0e-7
                    axes = ",".join(item[0] for item in joint_info)
                    print(
                        f"NoitomPinkJointDebug side={side} axes={axes} "
                        f"actual_rad={_fmt_tensor(actual_joints)} "
                        f"ik_target_rad={_fmt_tensor(ik_targets)} "
                        f"safe_margin_rad={_fmt_tensor(margins)} "
                        f"ik_step_max_rad={ik_step_max_rad:.6f} "
                        f"solver_held={int(solver_held)}"
                    )

    return NoitomPinkInverseKinematicsAction


def _configure_noitom_pink_ik(
    env_cfg: NoitomLocomanipulationG1EnvCfg,
    use_arm_frames: bool,
    pink_task_gain: float,
    pink_lm_damping: float,
    orientation_debug: bool,
    print_period_s: float,
    draw_wrist_frames: bool,
    wrist_frame_axis_length: float,
    wrist_pitch_limit_deg: float,
    wrist_yaw_limit_deg: float,
    ik_config_path: str | None,
) -> None:
    """Tune Pink IK and add torso plus optional elbow/shoulder frame tasks."""
    from isaaclab.controllers.pink_ik import LocalFrameTaskCfg, NullSpacePostureTaskCfg

    if not 0.0 < pink_task_gain <= 1.0:
        raise ValueError("NOITOM_PINK_TASK_GAIN must be in (0, 1]")
    if pink_lm_damping < 0.0:
        raise ValueError("NOITOM_PINK_LM_DAMPING must be nonnegative")
    if ik_config_path is None:
        raise ValueError("Noitom Pink task weights require an IK config")

    env_cfg.actions.upper_body_ik.class_type = _build_noitom_pink_ik_action_class(
        orientation_debug,
        print_period_s,
        draw_wrist_frames,
        wrist_frame_axis_length,
        wrist_pitch_limit_deg,
        wrist_yaw_limit_deg,
    )
    controller = env_cfg.actions.upper_body_ik.controller
    controller.show_ik_warnings = orientation_debug
    ik_config = load_noitom_ik_config(ik_config_path)
    task_weights = ik_config.pink_task_weights

    def configured_cost(frame: str, role: str, *, rotation: bool = False) -> float:
        side = "left" if "left" in frame else "right"
        mapping = ik_config.match(side, role)
        return mapping.rotation_weight if rotation else mapping.position_weight

    tasks = list(controller.variable_input_tasks)
    wrist_task_count = sum(1 for task in tasks if isinstance(task, LocalFrameTaskCfg))
    extra_frame_tasks = [
        LocalFrameTaskCfg(
            frame=_PINK_TORSO_LINK,
            base_link_frame_name=_PINK_PELVIS_LINK,
            position_cost=task_weights.torso_position,
            orientation_cost=task_weights.torso_rotation,
            lm_damping=pink_lm_damping,
            gain=pink_task_gain,
        )
    ]
    if use_arm_frames:
        extra_frame_tasks.extend(
            [
                LocalFrameTaskCfg(
                    frame=_PINK_LEFT_ELBOW_LINK,
                    base_link_frame_name=_PINK_PELVIS_LINK,
                    position_cost=configured_cost(_PINK_LEFT_ELBOW_LINK, "elbow"),
                    orientation_cost=configured_cost(
                        _PINK_LEFT_ELBOW_LINK, "elbow", rotation=True
                    ),
                    lm_damping=pink_lm_damping,
                    gain=pink_task_gain,
                ),
                LocalFrameTaskCfg(
                    frame=_PINK_RIGHT_ELBOW_LINK,
                    base_link_frame_name=_PINK_PELVIS_LINK,
                    position_cost=configured_cost(_PINK_RIGHT_ELBOW_LINK, "elbow"),
                    orientation_cost=configured_cost(
                        _PINK_RIGHT_ELBOW_LINK, "elbow", rotation=True
                    ),
                    lm_damping=pink_lm_damping,
                    gain=pink_task_gain,
                ),
                LocalFrameTaskCfg(
                    frame=_PINK_LEFT_SHOULDER_LINK,
                    base_link_frame_name=_PINK_PELVIS_LINK,
                    position_cost=configured_cost(_PINK_LEFT_SHOULDER_LINK, "shoulder"),
                    orientation_cost=configured_cost(
                        _PINK_LEFT_SHOULDER_LINK, "shoulder", rotation=True
                    ),
                    lm_damping=pink_lm_damping,
                    gain=pink_task_gain,
                ),
                LocalFrameTaskCfg(
                    frame=_PINK_RIGHT_SHOULDER_LINK,
                    base_link_frame_name=_PINK_PELVIS_LINK,
                    position_cost=configured_cost(
                        _PINK_RIGHT_SHOULDER_LINK, "shoulder"
                    ),
                    orientation_cost=configured_cost(
                        _PINK_RIGHT_SHOULDER_LINK, "shoulder", rotation=True
                    ),
                    lm_damping=pink_lm_damping,
                    gain=pink_task_gain,
                ),
            ]
        )
    controller.variable_input_tasks = (
        tasks[:wrist_task_count] + extra_frame_tasks + tasks[wrist_task_count:]
    )

    for task in controller.variable_input_tasks:
        if isinstance(task, LocalFrameTaskCfg):
            frame = task.frame
            task.gain = pink_task_gain
            task.lm_damping = pink_lm_damping
            if "wrist" in frame:
                task.position_cost = configured_cost(frame, "wrist")
                task.orientation_cost = configured_cost(frame, "wrist", rotation=True)
            elif frame == _PINK_TORSO_LINK:
                task.position_cost = task_weights.torso_position
                task.orientation_cost = task_weights.torso_rotation
            elif "elbow" in frame:
                task.position_cost = configured_cost(frame, "elbow")
                task.orientation_cost = configured_cost(frame, "elbow", rotation=True)
            elif "shoulder" in frame:
                task.position_cost = configured_cost(frame, "shoulder")
                task.orientation_cost = configured_cost(
                    frame, "shoulder", rotation=True
                )
            else:
                raise ValueError(f"No Pink task weights configured for frame {frame!r}")
        elif isinstance(task, NullSpacePostureTaskCfg):
            task.cost = task_weights.null_space_posture
            task.gain = pink_task_gain
            task.lm_damping = pink_lm_damping


def register_tasks() -> list[str]:
    """Register the Noitom G1 locomanipulation task with Gymnasium."""
    if TASK_ID not in registry:
        gym.register(
            id=TASK_ID,
            entry_point="isaaclab.envs:ManagerBasedRLEnv",
            kwargs={
                "env_cfg_entry_point": ("noitom_tasks:NoitomLocomanipulationG1EnvCfg"),
            },
            disable_env_checker=True,
        )
    return []


@configclass
class NoitomLocomanipulationG1EnvCfg(LocomanipulationG1EnvCfg):
    """G1 locomanipulation config using Noitom mocap as the IsaacTeleop source."""

    def __post_init__(self) -> None:
        """Use the base scene/action config and swap in the Noitom pipeline."""
        super().__post_init__()
        settings = _noitom_settings_from_env()
        settings = replace(
            settings,
            retargeting=replace(
                settings.retargeting,
                robot_pelvis_quat_xyzw=np.asarray(
                    self.scene.robot.init_state.rot, dtype=np.float64
                ),
            ),
        )
        self.isaac_teleop.pipeline_builder = lambda: (
            build_noitom_g1_locomanipulation_pipeline(settings)
        )
        self.isaac_teleop.plugins = _noitom_plugin_configs(settings)
        if settings.clear_workspace:
            del self.scene.packing_table
            self.scene.object.init_state.pos = (3.0, 3.0, 1.0)
            self.scene.object.spawn.rigid_props.disable_gravity = True
            self.terminations.object_dropping = None
            self.terminations.object_too_far = None
            self.terminations.success = None
            print("NoitomG1Env: removed packing_table and parked object at [3, 3, 1]")
        robot_world_offset = np.asarray(settings.robot_world_offset, dtype=np.float64)
        if np.any(robot_world_offset != 0.0):
            initial_position = np.asarray(
                self.scene.robot.init_state.pos, dtype=np.float64
            )
            self.scene.robot.init_state.pos = tuple(
                initial_position + robot_world_offset
            )
            print(
                "NoitomG1Env: shifted robot/reference/IK anchors "
                f"offset={_fmt_vec(robot_world_offset)}"
            )
        # Fixed-root upper-body teleoperation: the inherited Agile term must be
        # removed before managers are instantiated, while waist remains in Pink.
        self.scene.robot.spawn.articulation_props.fix_root_link = True
        self.actions.lower_body_joint_pos = None
        self.observations.lower_body_policy = None
        # Pink IK: wrists plus an orientation-only torso task, with optional
        # elbow/shoulder position tasks. Root stays fixed while waist remains in IK.
        _configure_noitom_pink_ik(
            self,
            use_arm_frames=settings.use_arm_ik_frame_tasks,
            pink_task_gain=settings.pink_task_gain,
            pink_lm_damping=settings.pink_lm_damping,
            orientation_debug=settings.orientation_debug,
            print_period_s=settings.print_period_s,
            draw_wrist_frames=settings.draw_wrist_frames,
            wrist_frame_axis_length=settings.wrist_frame_axis_length,
            wrist_pitch_limit_deg=settings.wrist_pitch_limit_deg,
            wrist_yaw_limit_deg=settings.wrist_yaw_limit_deg,
            ik_config_path=settings.retargeting.ik_config_path,
        )
        self.isaac_teleop.teleoperation_active_default = (
            settings.teleoperation_active_default
        )
        self.isaac_teleop.control_channel_uuid = None
        self.isaac_teleop.app_name = "IsaacLabNoitomG1"
        print(
            "NoitomG1Env: lower_body=fixed root_fixed=1 "
            "leg_action=disabled "
            f"action_dim={g1_action_dim(use_arm_ik_frame_tasks=settings.use_arm_ik_frame_tasks)}"
        )


def G1LocomanipulationAction(*, use_arm_ik_frame_tasks: bool = True) -> TensorGroupType:
    """G1 locomanipulation action tensor type."""
    return TensorGroupType(
        "g1_locomanipulation_action",
        [
            NDArrayType(
                "action",
                shape=(g1_action_dim(use_arm_ik_frame_tasks=use_arm_ik_frame_tasks),),
                dtype=DLDataType.FLOAT,
                dtype_bits=32,
            ),
        ],
    )


class NoitomG1ActionSource(IDeviceIOSource):
    """Convert Noitom mocap frames into G1 upper-body task-space actions."""

    def __init__(
        self,
        name: str = "noitom_g1_action",
        settings: NoitomG1Settings = DEFAULT_NOITOM_G1_SETTINGS,
    ) -> None:
        """Initialize the Noitom DeviceIO tracker and retargeter."""
        import isaacteleop.deviceio as deviceio

        self._tracker = deviceio.FullBodyTracker()
        vendor = deviceio.TrackerVendor(
            _NOITOM_VENDOR_ID,
            {
                "collection_id": settings.collection_id,
                "max_flatbuffer_size": str(settings.max_flatbuffer_size),
            },
        )
        self._collection_id = settings.collection_id
        self._enable_motion = settings.enable_motion
        self._print_period_s = max(0.0, settings.print_period_s)
        self._last_print_s = 0.0
        self._reference_viz = _NoitomReferenceVisualizer(settings)
        self._retargeter = NoitomG1Retargeter(settings.retargeting)
        self._use_arm_ik_frame_tasks = settings.use_arm_ik_frame_tasks
        self._hold_targets = self._retargeter.current_arm_targets
        self._frame_count = 0
        self._calibration_attempts = 0
        self._no_data_count = 0
        self._first_frame_printed = False
        self._first_valid_wrist_pose_printed = False
        self._calibration_fail_count = 0
        self._orientation_debug = settings.orientation_debug
        self._previous_orientation_debug_time_s: float | None = None
        self._previous_orientation_debug_quaternions: dict[
            str, tuple[np.ndarray, np.ndarray]
        ] = {}
        super().__init__(name, vendor=vendor)

    def get_tracker(self):
        """Return the Noitom mocap tracker used by this source."""
        return self._tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll Noitom data from the active DeviceIO session."""
        tracked = self._tracker.get_body_pose(deviceio_session)
        group = TensorGroup(self.input_spec()[_FULL_BODY_INPUT])
        group[0] = tracked
        return {_FULL_BODY_INPUT: group}

    def input_spec(self) -> RetargeterIOType:
        """Declare the raw full-body DeviceIO input."""
        return {_FULL_BODY_INPUT: DeviceIOFullBodyPoseTracked()}

    def output_spec(self) -> RetargeterIOType:
        """Declare the flattened G1 action output."""
        return {
            _ACTION_OUTPUT: G1LocomanipulationAction(
                use_arm_ik_frame_tasks=self._use_arm_ik_frame_tasks
            )
        }

    def _compute_fn(
        self,
        inputs: RetargeterIO,
        outputs: RetargeterIO,
        context: ComputeContext,
    ) -> None:
        """Convert a pushed full-body frame into the G1 action tensor."""
        self._frame_count += 1

        if context.execution_events.reset:
            self._retargeter.clear_calibration()
            self._calibration_attempts = 0
            self._no_data_count = 0
            self._calibration_fail_count = 0
            self._previous_orientation_debug_time_s = None
            self._previous_orientation_debug_quaternions.clear()
            self._reset_wrist_pose_debug_state()
            print(
                "NoitomG1ActionSource: cleared retargeting calibration "
                f"collection={self._collection_id}"
            )

        # Read the raw tracked data from DeviceIO
        frame: FullBodyPose | None = inputs[_FULL_BODY_INPUT][0]

        # --- First-frame diagnostic ---
        if not self._first_frame_printed:
            self._first_frame_printed = True
            print(
                "NoitomG1ActionSource: first frame "
                f"collection={self._collection_id} "
                f"has_data={frame is not None} "
                f"motion_enabled={self._enable_motion}"
            )

        # --- No data warning ---
        if frame is None:
            self._no_data_count += 1
            if self._no_data_count == 1 or self._no_data_count % 300 == 0:
                print(
                    f"NoitomG1ActionSource: WARNING no data from tracker "
                    f"collection={self._collection_id} "
                    f"no_data_frames={self._no_data_count}/{self._frame_count} "
                    f"(is the noitom_mocap plugin running with matching collection_id?)"
                )
            # Still output hold pose even without data
            body_yaw_delta = self._retargeter.body_yaw_delta
            action = _make_action(
                self._hold_targets,
                use_arm_ik_frame_tasks=self._use_arm_ik_frame_tasks,
            )
            outputs[_ACTION_OUTPUT][0] = np.ascontiguousarray(action, dtype=np.float32)
            return

        # Reset no-data counter when we get valid frames
        self._no_data_count = 0

        if not self._enable_motion:
            body_yaw_delta = self._retargeter.body_yaw_delta
            action = _make_action(
                self._hold_targets,
                use_arm_ik_frame_tasks=self._use_arm_ik_frame_tasks,
            )
            outputs[_ACTION_OUTPUT][0] = np.ascontiguousarray(action, dtype=np.float32)
            self._reference_viz.update(frame, self._retargeter)
            self._print_status(frame, body_yaw_delta, context)
            return

        # --- Calibration / retarget phase ---
        if self._retargeter.awaiting_calibration:
            self._calibration_attempts += 1
            success = self._retargeter.calibrate(frame)
            if success:
                self._hold_targets = self._retargeter.current_arm_targets
                print(
                    "NoitomG1ActionSource: calibrated neutral pose "
                    f"collection={self._collection_id} "
                    f"attempts={self._calibration_attempts}"
                )
            else:
                self._calibration_fail_count += 1
                if (
                    self._calibration_fail_count == 1
                    or self._calibration_fail_count % 150 == 0
                ):
                    # Diagnose WHY calibration is failing
                    diag = _calibration_diagnostics(frame)
                    print(
                        f"NoitomG1ActionSource: calibration attempt "
                        f"{self._calibration_attempts} failed {diag}"
                    )
        else:
            result = self._retargeter.retarget(frame)
            if result is not None:
                self._hold_targets = result

        body_yaw_delta = self._retargeter.body_yaw_delta
        action = _make_action(
            self._hold_targets,
            use_arm_ik_frame_tasks=self._use_arm_ik_frame_tasks,
        )
        outputs[_ACTION_OUTPUT][0] = np.ascontiguousarray(action, dtype=np.float32)

        self._maybe_print_first_valid_wrist_pose(frame, action)
        self._reference_viz.update(frame, self._retargeter)
        self._print_status(frame, body_yaw_delta, context)

    def _reset_wrist_pose_debug_state(self) -> None:
        self._first_valid_wrist_pose_printed = False

    def _maybe_print_first_valid_wrist_pose(
        self, frame: FullBodyPose, action: np.ndarray
    ) -> None:
        if (
            not self._orientation_debug
            or self._first_valid_wrist_pose_printed
            or not self._retargeter.is_calibrated
        ):
            return
        diagnostics = self._retargeter.wrist_pose_diagnostics(frame)
        if diagnostics is None:
            return

        for side, action_start in (("left", 0), ("right", 7)):
            raw_pose = diagnostics[side].bvh_raw_isaac_world.as_action_pose()
            aligned_raw_pose = diagnostics[side].bvh_aligned_raw_world.as_action_pose()
            semantic_pose = diagnostics[side].bvh_semantic_world.as_action_pose()
            target_pose = np.asarray(
                action[action_start : action_start + 7], dtype=np.float64
            )
            _raw_semantic_pos_error, raw_semantic_rot_error = _pose_error(
                aligned_raw_pose, semantic_pose
            )
            pos_error, rot_error = _pose_error(semantic_pose, target_pose)
            for stage, pose in (
                ("bvh_raw_isaac_world", raw_pose),
                ("bvh_aligned_raw_world", aligned_raw_pose),
                ("bvh_semantic_world", semantic_pose),
                ("retarget_target_world", target_pose),
            ):
                print(
                    f"NoitomWristPoseDebug sample=first_valid "
                    f"source_frame={self._frame_count} stage={stage} side={side} "
                    f"{_fmt_pose_debug(pose)}"
                )
            print(
                f"NoitomWristPoseError sample=first_valid "
                f"source_frame={self._frame_count} side={side} "
                f"raw_to_semantic_rot_deg={raw_semantic_rot_error:.6f} "
                f"semantic_to_retarget_pos_m={pos_error:.6f} "
                f"semantic_to_retarget_rot_deg={rot_error:.6f}"
            )
            print(
                f"NoitomWristAxisDebug sample=first_valid "
                f"source_frame={self._frame_count} side={side} "
                f"raw_x_dot_forearm="
                f"{_fmt_optional_float(diagnostics[side].raw_x_dot_forearm)} "
                f"semantic_x_dot_forearm="
                f"{_fmt_optional_float(diagnostics[side].semantic_x_dot_forearm)} "
                f"semantic_x_world="
                f"{_fmt_array(diagnostics[side].semantic_x_world, precision=6)} "
                f"semantic_y_world="
                f"{_fmt_array(diagnostics[side].semantic_y_world, precision=6)} "
                f"semantic_z_world="
                f"{_fmt_array(diagnostics[side].semantic_z_world, precision=6)} "
                f"local_offset_xyzw="
                f"{_fmt_array(diagnostics[side].local_offset_xyzw, precision=6)}"
            )
        self._first_valid_wrist_pose_printed = True

    def _print_status(
        self, frame: FullBodyPose, body_yaw_delta: float, context: ComputeContext
    ) -> None:
        if self._print_period_s <= 0.0:
            return
        now_s = context.graph_time.real_time_ns * 1.0e-9
        if now_s - self._last_print_s < self._print_period_s:
            return

        self._last_print_s = now_s
        motion = "on" if self._enable_motion else "off"
        calib = "ready" if self._retargeter.is_calibrated else "awaiting_neutral"
        left_pose = self._hold_targets.left_wrist.as_action_pose()
        right_pose = self._hold_targets.right_wrist.as_action_pose()
        torso_pose = self._hold_targets.torso.as_action_pose()
        frame_info = ""
        if self._use_arm_ik_frame_tasks:
            left_elbow_pose = self._hold_targets.left_elbow.as_action_pose()
            right_elbow_pose = self._hold_targets.right_elbow.as_action_pose()
            left_shoulder_pose = self._hold_targets.left_shoulder.as_action_pose()
            right_shoulder_pose = self._hold_targets.right_shoulder.as_action_pose()
            frame_info = (
                f" target_left_elbow={_fmt_pose(left_elbow_pose)}"
                f" target_right_elbow={_fmt_pose(right_elbow_pose)}"
                f" target_left_shoulder={_fmt_pose(left_shoulder_pose)}"
                f" target_right_shoulder={_fmt_pose(right_shoulder_pose)}"
            )
        print(
            "NoitomG1ActionSource: "
            f"joints={_valid_joint_count(frame)}/{int(BodyJoint.NUM_JOINTS)} "
            f"motion={motion} calibrated={calib} "
            f"yaw_delta={body_yaw_delta:+.3f} "
            f"motion_scale={self._retargeter.retargeting_settings.motion_scale:.2f} "
            f"wrist_orientation_mode="
            f"{self._retargeter.retargeting_settings.wrist_orientation_mode} "
            f"torso_yaw_influence={self._retargeter.retargeting_settings.torso_yaw_arm_influence:.2f} "
            f"target_torso_quat={_fmt_quat(torso_pose[3:7])} "
            f"target_left={_fmt_pose(left_pose)} target_right={_fmt_pose(right_pose)}"
            f"{frame_info} "
            f"{_raw_full_body_status(frame)}"
        )
        if self._orientation_debug:
            self._print_orientation_debug(frame, now_s)

    def _print_orientation_debug(self, frame: FullBodyPose, now_s: float) -> None:
        diagnostics = self._retargeter.wrist_orientation_diagnostics(frame)
        if diagnostics is None:
            return
        elapsed_s = (
            None
            if self._previous_orientation_debug_time_s is None
            else now_s - self._previous_orientation_debug_time_s
        )
        for side, diagnostic in diagnostics.items():
            world_speed = 0.0
            target_speed = 0.0
            previous = self._previous_orientation_debug_quaternions.get(side)
            if previous is not None and elapsed_s is not None and elapsed_s > 1.0e-6:
                world_speed = (
                    _quaternion_distance_deg(
                        previous[0], diagnostic.world_quaternion_xyzw
                    )
                    / elapsed_s
                )
                target_speed = (
                    _quaternion_distance_deg(
                        previous[1], diagnostic.target_quaternion_xyzw
                    )
                    / elapsed_s
                )
            world_delta_angle = float(np.linalg.norm(diagnostic.world_delta_rotvec_deg))
            torso_delta_angle = float(np.linalg.norm(diagnostic.torso_delta_rotvec_deg))
            print(
                f"NoitomOrientationDebug side={side} "
                f"world_q={_fmt_quat(diagnostic.world_quaternion_xyzw)} "
                f"reference_q={_fmt_quat(diagnostic.reference_quaternion_xyzw)} "
                f"torso_q={_fmt_quat(diagnostic.torso_quaternion_xyzw)} "
                f"world_delta_rotvec_deg={_fmt_vec(diagnostic.world_delta_rotvec_deg)} "
                f"world_delta_deg={world_delta_angle:.2f} "
                f"torso_delta_rotvec_deg={_fmt_vec(diagnostic.torso_delta_rotvec_deg)} "
                f"torso_delta_deg={torso_delta_angle:.2f} "
                f"forearm_swing_deg={diagnostic.forearm_swing_deg:.2f} "
                f"twist_deg={diagnostic.twist_deg:+.2f} "
                f"bounded_twist_deg={diagnostic.bounded_twist_deg:+.2f} "
                f"source_target_error_deg={diagnostic.source_target_error_deg:.2f} "
                f"target_q={_fmt_quat(diagnostic.target_quaternion_xyzw)} "
                f"world_speed_deg_s={world_speed:.2f} "
                f"target_speed_deg_s={target_speed:.2f}"
            )
            print(
                f"NoitomWristAxisDebug side={side} "
                f"raw_x_dot_forearm="
                f"{_fmt_optional_float(diagnostic.raw_x_dot_forearm)} "
                f"semantic_x_dot_forearm="
                f"{_fmt_optional_float(diagnostic.semantic_x_dot_forearm)} "
                f"semantic_x_world="
                f"{_fmt_array(diagnostic.semantic_x_world, precision=6)} "
                f"semantic_y_world="
                f"{_fmt_array(diagnostic.semantic_y_world, precision=6)} "
                f"semantic_z_world="
                f"{_fmt_array(diagnostic.semantic_z_world, precision=6)} "
                f"local_offset_xyzw="
                f"{_fmt_array(diagnostic.local_offset_xyzw, precision=6)}"
            )
            self._previous_orientation_debug_quaternions[side] = (
                diagnostic.world_quaternion_xyzw.copy(),
                diagnostic.target_quaternion_xyzw.copy(),
            )
        self._previous_orientation_debug_time_s = now_s


def build_noitom_g1_locomanipulation_pipeline(
    settings: NoitomG1Settings = DEFAULT_NOITOM_G1_SETTINGS,
) -> OutputCombiner:
    """Build a one-source IsaacTeleop pipeline for Noitom G1 testing."""
    source = NoitomG1ActionSource(settings=settings)
    return OutputCombiner({_ACTION_OUTPUT: source.output(_ACTION_OUTPUT)})


def _make_action(
    targets: ArmIkTargets,
    *,
    use_arm_ik_frame_tasks: bool,
) -> np.ndarray:
    action = np.zeros(
        g1_action_dim(use_arm_ik_frame_tasks=use_arm_ik_frame_tasks),
        dtype=np.float32,
    )
    action[0:7] = targets.left_wrist.as_action_pose()
    action[7:14] = targets.right_wrist.as_action_pose()
    action[14:21] = targets.torso.as_action_pose()
    hand_offset = 21
    if use_arm_ik_frame_tasks:
        action[21:28] = targets.left_elbow.as_action_pose()
        action[28:35] = targets.right_elbow.as_action_pose()
        action[35:42] = targets.left_shoulder.as_action_pose()
        action[42:49] = targets.right_shoulder.as_action_pose()
        hand_offset = 49
    action[hand_offset : hand_offset + 14] = 0.0
    return action


class _NoitomReferenceVisualizer:
    """Draw the incoming Noitom frame as a Kit debug-draw stick figure."""

    def __init__(self, settings: NoitomG1Settings) -> None:
        self._enabled = settings.draw_reference
        self._draw: Any | None = None
        self._warned = False
        self._printed_first_draw = False
        self._scale = settings.draw_scale
        self._offset = np.array(settings.draw_offset, dtype=np.float32)
        self._pelvis_relative = settings.draw_pelvis_relative
        self._pelvis_anchor = np.array(settings.draw_pelvis_anchor, dtype=np.float32)
        self._draw_wrist_targets = settings.draw_wrist_targets
        self._draw_wrist_frames = settings.draw_wrist_frames
        self._wrist_frame_axis_length = max(0.01, settings.wrist_frame_axis_length)
        self._draw_elbow_targets = (
            settings.draw_elbow_targets and settings.use_arm_ik_frame_tasks
        )
        self._draw_shoulder_targets = (
            settings.draw_shoulder_targets and settings.use_arm_ik_frame_tasks
        )
        self._retargeting = settings.retargeting

    def update(
        self,
        frame: FullBodyPose,
        retargeter: NoitomG1Retargeter,
    ) -> None:
        if not self._enabled:
            return
        draw = self._get_draw_interface()
        if draw is None:
            return

        calib_view = retargeter.calibration_view
        draw_positions = self._reference_positions(frame, calib_view, retargeter)
        starts: list[list[float]] = []
        ends: list[list[float]] = []
        colors: list[tuple[float, float, float, float]] = []
        thicknesses: list[float] = []

        for parent_index, child_index in _FULL_BODY_BONES:
            parent = draw_positions.get(int(parent_index))
            child = draw_positions.get(int(child_index))
            if parent is None or child is None:
                continue
            starts.append(parent.tolist())
            ends.append(child.tolist())
            colors.append(_NOITOM_REFERENCE_COLOR)
            thicknesses.append(_NOITOM_REFERENCE_LINE_THICKNESS)

        marker_starts, marker_ends, marker_colors = self._joint_markers(draw_positions)
        starts.extend(marker_starts)
        ends.extend(marker_ends)
        colors.extend(marker_colors)
        thicknesses.extend([_NOITOM_REFERENCE_LINE_THICKNESS] * len(marker_starts))

        if self._draw_wrist_targets:
            wrist_starts, wrist_ends, wrist_colors = self._frame_highlight_markers(
                draw_positions,
                (
                    int(BodyJoint.LEFT_WRIST),
                    int(BodyJoint.RIGHT_WRIST),
                ),
                _NOITOM_WRIST_TARGET_COLOR,
                _NOITOM_WRIST_TARGET_MARKER_SIZE,
            )
            starts.extend(wrist_starts)
            ends.extend(wrist_ends)
            colors.extend(wrist_colors)
            thicknesses.extend([_NOITOM_REFERENCE_LINE_THICKNESS] * len(wrist_starts))

        if self._draw_wrist_frames:
            for side, wrist_frame in retargeter.reference_wrist_frames(frame).items():
                wrist_index = int(
                    BodyJoint.LEFT_WRIST if side == "left" else BodyJoint.RIGHT_WRIST
                )
                position = draw_positions.get(wrist_index)
                if position is None:
                    continue
                axis_starts, axis_ends, axis_colors = self._coordinate_axes(
                    position.astype(np.float32),
                    wrist_frame.quaternion_xyzw,
                )
                starts.extend(axis_starts)
                ends.extend(axis_ends)
                colors.extend(axis_colors)
                thicknesses.extend([5.0] * len(axis_starts))

        if self._draw_elbow_targets:
            elbow_starts, elbow_ends, elbow_colors = self._frame_highlight_markers(
                draw_positions,
                (
                    int(BodyJoint.LEFT_ELBOW),
                    int(BodyJoint.RIGHT_ELBOW),
                ),
                _NOITOM_ELBOW_TARGET_COLOR,
                _NOITOM_ELBOW_TARGET_MARKER_SIZE,
            )
            starts.extend(elbow_starts)
            ends.extend(elbow_ends)
            colors.extend(elbow_colors)
            thicknesses.extend([_NOITOM_REFERENCE_LINE_THICKNESS] * len(elbow_starts))

        if self._draw_shoulder_targets:
            shoulder_starts, shoulder_ends, shoulder_colors = (
                self._frame_highlight_markers(
                    draw_positions,
                    (
                        int(BodyJoint.LEFT_SHOULDER),
                        int(BodyJoint.RIGHT_SHOULDER),
                    ),
                    _NOITOM_SHOULDER_TARGET_COLOR,
                    _NOITOM_SHOULDER_TARGET_MARKER_SIZE,
                )
            )
            starts.extend(shoulder_starts)
            ends.extend(shoulder_ends)
            colors.extend(shoulder_colors)
            thicknesses.extend(
                [_NOITOM_REFERENCE_LINE_THICKNESS] * len(shoulder_starts)
            )

        draw.clear_lines()
        if starts:
            draw.draw_lines(starts, ends, colors, thicknesses)
            if not self._printed_first_draw:
                anchor = (
                    _fmt_vec(self._pelvis_anchor)
                    if self._pelvis_relative
                    else "disabled"
                )
                print(
                    "NoitomG1ActionSource: drawing Noitom reference skeleton "
                    f"segments={len(starts)} joints={len(draw_positions)} "
                    f"pelvis_relative={self._pelvis_relative} "
                    f"robot_pelvis_anchor={anchor}; BVH wrist axes "
                    "X=red Y=green Z=blue"
                )
                self._printed_first_draw = True
        elif not self._warned:
            print(
                "NoitomG1ActionSource: reference visualizer found no drawable "
                "Noitom bones or joints"
            )
            self._warned = True

    def _get_draw_interface(self) -> Any | None:
        if self._draw is not None:
            return self._draw
        try:
            from isaacsim.core.experimental.utils.app import enable_extension

            enable_extension("isaacsim.util.debug_draw")
            from isaacsim.util.debug_draw import _debug_draw as omni_debug_draw

            self._draw = omni_debug_draw.acquire_debug_draw_interface()
        except (ImportError, AttributeError, RuntimeError, ModuleNotFoundError):
            try:
                import omni.isaac.debug_draw._debug_draw as omni_debug_draw

                self._draw = omni_debug_draw.acquire_debug_draw_interface()
            except (
                ImportError,
                AttributeError,
                RuntimeError,
                ModuleNotFoundError,
            ) as exc:
                if not self._warned:
                    print(
                        "NoitomG1ActionSource: reference visualizer disabled "
                        f"({type(exc).__name__}: {exc})"
                    )
                    self._warned = True
                return None
        except Exception as exc:
            if not self._warned:
                print(
                    "NoitomG1ActionSource: reference visualizer disabled "
                    f"({type(exc).__name__}: {exc})"
                )
                self._warned = True
            return None
        return self._draw

    def _reference_positions(
        self,
        frame: FullBodyPose,
        calib_view: Any | None,
        retargeter: NoitomG1Retargeter,
    ) -> dict[int, np.ndarray]:
        if self._pelvis_relative:
            rt = self._retargeting
            if rt.ik_config_path is not None:
                positions = retargeter.reference_skeleton_positions(frame)
                return {
                    index: (pos + self._offset).astype(np.float32)
                    for index, pos in positions.items()
                }
            positions = aligned_reference_skeleton_from_frame(
                frame,
                self._pelvis_anchor,
                draw_scale=self._scale,
                calib_view=(
                    calib_view if not rt.reference_use_robot_link_lengths else None
                ),
                use_robot_link_lengths=rt.reference_use_robot_link_lengths,
                link_lengths=ReferenceSkeletonLengths.from_retargeting_settings(rt),
                length_scale=rt.reference_length_scale,
                arm_length_scale=rt.reference_arm_length_scale,
                shoulder_span_scale=rt.reference_shoulder_span_scale,
            )
            return {
                index: (pos + self._offset).astype(np.float32)
                for index, pos in positions.items()
            }

        raw_positions = _joint_position_map(frame)
        return {
            index: (
                self._offset
                + noitom_position_to_isaac(point).astype(np.float32) * self._scale
            )
            for index, point in raw_positions.items()
        }

    def _joint_markers(
        self,
        positions: dict[int, np.ndarray],
    ) -> tuple[_LineList, _LineList, _ColorList]:
        starts: _LineList = []
        ends: _LineList = []
        colors: _ColorList = []
        marker_delta_x = np.array([_NOITOM_REFERENCE_JOINT_MARKER_SIZE, 0.0, 0.0])
        marker_delta_y = np.array([0.0, _NOITOM_REFERENCE_JOINT_MARKER_SIZE, 0.0])
        marker_delta_z = np.array([0.0, 0.0, _NOITOM_REFERENCE_JOINT_MARKER_SIZE])
        for position in positions.values():
            point = position.astype(np.float32)
            for marker_delta in (marker_delta_x, marker_delta_y, marker_delta_z):
                starts.append((point - marker_delta).tolist())
                ends.append((point + marker_delta).tolist())
                colors.append(_NOITOM_REFERENCE_COLOR)
        return starts, ends, colors

    def _frame_highlight_markers(
        self,
        draw_positions: dict[int, np.ndarray],
        joint_indices: tuple[int, ...],
        color: tuple[float, float, float, float],
        marker_size: float,
    ) -> tuple[_LineList, _LineList, _ColorList]:
        """Highlight selected joints on the cyan skeleton."""
        starts: _LineList = []
        ends: _LineList = []
        colors: _ColorList = []
        marker_delta_x = np.array([marker_size, 0.0, 0.0])
        marker_delta_y = np.array([0.0, marker_size, 0.0])
        marker_delta_z = np.array([0.0, 0.0, marker_size])
        for joint_index in joint_indices:
            position = draw_positions.get(joint_index)
            if position is None:
                continue
            point = position.astype(np.float32)
            for marker_delta in (marker_delta_x, marker_delta_y, marker_delta_z):
                starts.append((point - marker_delta).tolist())
                ends.append((point + marker_delta).tolist())
                colors.append(color)
        return starts, ends, colors


def _joint_position_map(frame: FullBodyPose) -> dict[int, np.ndarray]:
    positions: dict[int, np.ndarray] = {}
    if frame.joints is None:
        return positions
    for index in range(int(BodyJoint.NUM_JOINTS)):
        position = _joint_position(frame, index)
        if position is not None:
            positions[index] = position
    return positions


def _joint_position(frame: FullBodyPose, joint_index: int) -> np.ndarray | None:
    if frame.joints is None:
        return None
    joint = frame.joints.joints(int(joint_index))
    if not joint.is_valid:
        return None
    value = _point_to_array(joint.pose.position)
    if np.all(np.isfinite(value)):
        return value
    return None


def _valid_joint_count(frame: FullBodyPose) -> int:
    if frame.joints is None:
        return 0
    count = 0
    for index in range(int(BodyJoint.NUM_JOINTS)):
        if frame.joints.joints(index).is_valid:
            count += 1
    return count


def _raw_full_body_status(frame: FullBodyPose) -> str:
    left_wrist = _joint_position(frame, BodyJoint.LEFT_WRIST)
    right_wrist = _joint_position(frame, BodyJoint.RIGHT_WRIST)
    pelvis = _joint_position(frame, BodyJoint.PELVIS)
    spine3 = _joint_position(frame, BodyJoint.SPINE3)
    left_shoulder = _joint_position(frame, BodyJoint.LEFT_SHOULDER)
    right_shoulder = _joint_position(frame, BodyJoint.RIGHT_SHOULDER)
    left_elbow = _joint_position(frame, BodyJoint.LEFT_ELBOW)
    right_elbow = _joint_position(frame, BodyJoint.RIGHT_ELBOW)

    missing = []
    if pelvis is None:
        missing.append("pelvis")
    if spine3 is None:
        missing.append("spine3")
    if left_shoulder is None:
        missing.append("l_shoulder")
    if right_shoulder is None:
        missing.append("r_shoulder")
    if left_elbow is None:
        missing.append("l_elbow")
    if right_elbow is None:
        missing.append("r_elbow")
    if left_wrist is None:
        missing.append("l_wrist")
    if right_wrist is None:
        missing.append("r_wrist")

    if missing:
        return f"upper_body_missing={','.join(missing)}"
    left_isaac = noitom_position_to_isaac(left_wrist)
    right_isaac = noitom_position_to_isaac(right_wrist)
    pelvis_isaac = noitom_position_to_isaac(pelvis)
    return (
        f"left_wrist={_fmt_vec(left_wrist)} right_wrist={_fmt_vec(right_wrist)} "
        f"isaac_left={_fmt_vec(left_isaac)} isaac_right={_fmt_vec(right_isaac)} "
        f"isaac_pelvis={_fmt_vec(pelvis_isaac)}"
    )


def _calibration_diagnostics(frame: FullBodyPose) -> str:
    """Detailed calibration diagnostics: which joints are valid/invalid."""
    pelvis = _joint_position(frame, BodyJoint.PELVIS)
    spine3 = _joint_position(frame, BodyJoint.SPINE3)
    left_shoulder = _joint_position(frame, BodyJoint.LEFT_SHOULDER)
    right_shoulder = _joint_position(frame, BodyJoint.RIGHT_SHOULDER)
    left_elbow = _joint_position(frame, BodyJoint.LEFT_ELBOW)
    right_elbow = _joint_position(frame, BodyJoint.RIGHT_ELBOW)
    left_wrist = _joint_position(frame, BodyJoint.LEFT_WRIST)
    right_wrist = _joint_position(frame, BodyJoint.RIGHT_WRIST)

    required = {
        "pelvis": pelvis,
        "spine3": spine3,
        "L_shoulder": left_shoulder,
        "R_shoulder": right_shoulder,
        "L_elbow": left_elbow,
        "R_elbow": right_elbow,
        "L_wrist": left_wrist,
        "R_wrist": right_wrist,
    }
    valid = [k for k, v in required.items() if v is not None]
    missing = [k for k, v in required.items() if v is None]
    total_joints = int(BodyJoint.NUM_JOINTS)
    all_valid = sum(
        1
        for i in range(total_joints)
        if frame.joints is not None and frame.joints.joints(i).is_valid
    )
    return (
        f"total_valid={all_valid}/{total_joints} "
        f"required_valid={len(valid)}/8 "
        f"missing=[{','.join(missing)}]"
        if missing
        else f"all_required_ok={valid}"
    )


def _point_to_array(point: Any) -> np.ndarray:
    return np.array([point.x, point.y, point.z], dtype=np.float32)


def _fmt_vec(vec: np.ndarray) -> str:
    return "[" + ", ".join(f"{v:+.3f}" for v in vec) + "]"


def _fmt_quat(quat: np.ndarray) -> str:
    return "[" + ", ".join(f"{v:+.4f}" for v in quat) + "]"


def _fmt_array(values: np.ndarray, *, precision: int) -> str:
    return "[" + ", ".join(f"{value:+.{precision}f}" for value in values) + "]"


def _fmt_optional_float(value: float | None) -> str:
    return "skipped" if value is None else f"{value:+.6f}"


def _fmt_pose_debug(pose: np.ndarray) -> str:
    normalized = _normalized_pose_xyzw(pose)
    return (
        f"pos_m={_fmt_array(normalized[:3], precision=6)} "
        f"quat_xyzw={_fmt_array(normalized[3:7], precision=6)}"
    )


def _fmt_tensor(tensor: Any) -> str:
    values = tensor.detach().cpu().tolist()
    return "[" + ", ".join(f"{value:+.4f}" for value in values) + "]"


def _quaternion_matrix(quaternion_xyzw: np.ndarray) -> np.ndarray:
    quat = np.asarray(quaternion_xyzw, dtype=np.float64)
    quat /= max(float(np.linalg.norm(quat)), 1.0e-8)
    x, y, z, w = quat
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _quaternion_distance_deg(left: np.ndarray, right: np.ndarray) -> float:
    left_normalized = left / max(float(np.linalg.norm(left)), 1.0e-8)
    right_normalized = right / max(float(np.linalg.norm(right)), 1.0e-8)
    dot = float(np.clip(abs(np.dot(left_normalized, right_normalized)), 0.0, 1.0))
    return float(np.rad2deg(2.0 * np.arccos(dot)))


def _fmt_pose(pose: np.ndarray) -> str:
    return (
        f"pos=[{pose[0]:+.3f}, {pose[1]:+.3f}, {pose[2]:+.3f}] "
        f"quat=[{pose[3]:+.3f}, {pose[4]:+.3f}, {pose[5]:+.3f}, {pose[6]:+.3f}]"
    )


__all__ = [
    "TASK_ID",
    "NoitomG1ActionSource",
    "NoitomLocomanipulationG1EnvCfg",
    "build_noitom_g1_locomanipulation_pipeline",
    "g1_action_dim",
    "register_tasks",
]
