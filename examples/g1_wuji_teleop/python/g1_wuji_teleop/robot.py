# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MANUS and AVP data helpers for the G1-Wuji teleop example."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .config import example_root

LEFT_WUJI_JOINTS = (
    "left_finger1_joint1",
    "left_finger1_joint2",
    "left_finger1_joint3",
    "left_finger1_joint4",
    "left_finger2_joint1",
    "left_finger2_joint2",
    "left_finger2_joint3",
    "left_finger2_joint4",
    "left_finger3_joint1",
    "left_finger3_joint2",
    "left_finger3_joint3",
    "left_finger3_joint4",
    "left_finger4_joint1",
    "left_finger4_joint2",
    "left_finger4_joint3",
    "left_finger4_joint4",
    "left_finger5_joint1",
    "left_finger5_joint2",
    "left_finger5_joint3",
    "left_finger5_joint4",
)

RIGHT_WUJI_JOINTS = tuple(
    name.replace("left_", "right_", 1) for name in LEFT_WUJI_JOINTS
)

WUJI_SKELETON21_OPENXR_NAMES = (
    "wrist",
    "thumb_metacarpal",
    "thumb_proximal",
    "thumb_distal",
    "thumb_tip",
    "index_proximal",
    "index_intermediate",
    "index_distal",
    "index_tip",
    "middle_proximal",
    "middle_intermediate",
    "middle_distal",
    "middle_tip",
    "ring_proximal",
    "ring_intermediate",
    "ring_distal",
    "ring_tip",
    "little_proximal",
    "little_intermediate",
    "little_distal",
    "little_tip",
)

FIXED_WUJI_HAND_CONFIG_DIR = "wuji_retargeting"


def _default_wuji_initial_joint_positions() -> dict[str, float]:
    return {
        "left_finger1_joint1": 0.059,
        "left_finger1_joint2": 0.059,
        "left_finger1_joint3": 0.059,
        "left_finger1_joint4": 0.0,
        "left_finger2_joint1": 0.0,
        "left_finger2_joint2": 0.0,
        "left_finger2_joint3": 0.0,
        "left_finger2_joint4": 0.0,
        "left_finger3_joint1": 0.0,
        "left_finger3_joint2": 0.0,
        "left_finger3_joint3": 0.0,
        "left_finger3_joint4": 0.0,
        "left_finger4_joint1": 0.0,
        "left_finger4_joint2": 0.0,
        "left_finger4_joint3": 0.0,
        "left_finger4_joint4": 0.0,
        "left_finger5_joint1": 0.0,
        "left_finger5_joint2": 0.0,
        "left_finger5_joint3": 0.0,
        "left_finger5_joint4": 0.0,
        "right_finger1_joint1": 0.037,
        "right_finger1_joint2": 0.037,
        "right_finger1_joint3": 0.037,
        "right_finger1_joint4": 0.0,
        "right_finger2_joint1": 0.0,
        "right_finger2_joint2": 0.0,
        "right_finger2_joint3": 0.0,
        "right_finger2_joint4": 0.0,
        "right_finger3_joint1": 0.0,
        "right_finger3_joint2": 0.0,
        "right_finger3_joint3": 0.0,
        "right_finger3_joint4": 0.0,
        "right_finger4_joint1": 0.0,
        "right_finger4_joint2": 0.0,
        "right_finger4_joint3": 0.0,
        "right_finger4_joint4": 0.0,
        "right_finger5_joint1": 0.0,
        "right_finger5_joint2": 0.0,
        "right_finger5_joint3": 0.0,
        "right_finger5_joint4": 0.0,
    }


@dataclass(frozen=True)
class RobotProfile:
    variant: str
    robot_prim: str
    default_usd_relpath: str
    left_hand_joint_names: tuple[str, ...]
    right_hand_joint_names: tuple[str, ...]
    initial_hand_joint_positions: dict[str, float]
    hand_retarget_backend: str
    hand_wuji_config_dir: str | None
    ik_body_names: dict[str, str]
    ik_body_offset_pos: dict[str, tuple[float, float, float]]
    ik_body_offset_quat_xyzw: dict[str, tuple[float, float, float, float]]
    ik_target_orientation_correction_quat_xyzw: dict[
        str, tuple[float, float, float, float]
    ]
    reference_body: str
    reference_offset_pos: tuple[float, float, float]
    reference_offset_quat_xyzw: tuple[float, float, float, float]
    axis_signs: dict[str, float]
    status_label: str


ROBOT_PROFILES: dict[str, RobotProfile] = {
    "g1_wuji": RobotProfile(
        variant="g1_wuji",
        robot_prim="/World/G1Wuji",
        default_usd_relpath="assets/g1_wuji/g1_wuji.usd",
        left_hand_joint_names=LEFT_WUJI_JOINTS,
        right_hand_joint_names=RIGHT_WUJI_JOINTS,
        initial_hand_joint_positions=_default_wuji_initial_joint_positions(),
        hand_retarget_backend="official_wuji",
        hand_wuji_config_dir=FIXED_WUJI_HAND_CONFIG_DIR,
        ik_body_names={
            "left": "left_wrist_yaw_link",
            "right": "right_wrist_yaw_link",
        },
        ik_body_offset_pos={
            "left": (0.0415, 0.003, 0.0),
            "right": (0.0415, -0.003, 0.0),
        },
        ik_body_offset_quat_xyzw={
            "left": (0.0, 0.0, 0.0, 1.0),
            "right": (0.0, 0.0, 0.0, 1.0),
        },
        ik_target_orientation_correction_quat_xyzw={
            "left": (0.5, 0.5, 0.5, 0.5),
            "right": (-0.5, 0.5, 0.5, -0.5),
        },
        reference_body="torso_link",
        reference_offset_pos=(0.0077774, 0.0000210, 0.3836842),
        reference_offset_quat_xyzw=(0.0, 0.0, 0.0, 1.0),
        axis_signs={},
        status_label="G1-Wuji",
    ),
}


def normalize_robot_variant(value: Any) -> str:
    raw = str(value or "g1_wuji").strip().lower()
    if raw not in ROBOT_PROFILES:
        raise ValueError(
            f"Unsupported robot.variant={value!r}. Expected one of {sorted(ROBOT_PROFILES)}"
        )
    return raw


def robot_profile_from_config(config: Mapping[str, Any]) -> RobotProfile:
    robot_config = config.get("robot", {})
    if robot_config is None:
        robot_config = {}
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")
    return ROBOT_PROFILES[normalize_robot_variant(robot_config.get("variant"))]


@dataclass(frozen=True)
class WujiHandRuntimeConfig:
    robot_variant: str = "g1_wuji"
    neutral_calibration_samples: int = 30
    initial_joint_position: float = 0.0
    initial_joint_positions: dict[str, float] = field(
        default_factory=_default_wuji_initial_joint_positions
    )
    left_joint_names: tuple[str, ...] = LEFT_WUJI_JOINTS
    right_joint_names: tuple[str, ...] = RIGHT_WUJI_JOINTS
    axis_signs: dict[str, float] = field(default_factory=dict)
    retarget_backend: str = "official_wuji"
    status_label: str = "teleop"
    wuji_config_dir: Path | None = None
    retarget_output_mode: str = "absolute"
    clamp_to_joint_limits: bool = True
    smoothing_alpha: float = 0.8


@dataclass(frozen=True)
class AvpFrameBindingRuntimeConfig:
    status_label: str = "teleop"
    enabled: bool = True
    calibration_window_s: float = 3.0
    robot_reference_body: str = "torso_link"
    robot_reference_offset_pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    robot_reference_offset_quat_xyzw: tuple[float, float, float, float] = (
        0.0,
        0.0,
        0.0,
        1.0,
    )
    head_forward_axis_isaac: tuple[float, float, float] = (0.0, 1.0, 0.0)


@dataclass
class _AvpHeadHandBindingState:
    origin_pos: np.ndarray
    frame_rot: np.ndarray
    head_rot: np.ndarray


@dataclass
class _AvpPendingHeadHandCalibration:
    start_timestamp_s: float
    last_timestamp_s: float
    sample_count: int = 0
    head_pos_sum: np.ndarray = field(
        default_factory=lambda: np.zeros(3, dtype=np.float64)
    )
    head_rot_sum: np.ndarray = field(
        default_factory=lambda: np.zeros((3, 3), dtype=np.float64)
    )
    left_pos_sum: np.ndarray = field(
        default_factory=lambda: np.zeros(3, dtype=np.float64)
    )
    right_pos_sum: np.ndarray = field(
        default_factory=lambda: np.zeros(3, dtype=np.float64)
    )

    def append(
        self,
        *,
        timestamp_s: float,
        head_pos: np.ndarray,
        head_rot: np.ndarray,
        left_pos: np.ndarray,
        right_pos: np.ndarray,
    ) -> None:
        self.last_timestamp_s = float(timestamp_s)
        self.sample_count += 1
        self.head_pos_sum += np.asarray(head_pos, dtype=np.float64)
        self.head_rot_sum += np.asarray(head_rot, dtype=np.float64)
        self.left_pos_sum += np.asarray(left_pos, dtype=np.float64)
        self.right_pos_sum += np.asarray(right_pos, dtype=np.float64)


class HandTargetPostProcessor:
    """Map MANUS retarget qpos into stable USD joint position targets."""

    def __init__(
        self,
        *,
        joint_names: Sequence[str],
        initial_targets: np.ndarray,
        joint_limits: np.ndarray | None,
        config: WujiHandRuntimeConfig,
        side: str,
    ) -> None:
        self._joint_names = tuple(joint_names)
        self._initial_targets = np.asarray(initial_targets, dtype=np.float32)
        self._joint_limits = (
            None if joint_limits is None else np.asarray(joint_limits, dtype=np.float32)
        )
        self._config = config
        self._side = side
        self._neutral_samples: list[np.ndarray] = []
        self._neutral: np.ndarray | None = None
        self._last_target: np.ndarray | None = None
        self._announced = False

    @property
    def ready(self) -> bool:
        return (
            self._config.neutral_calibration_samples <= 0 or self._neutral is not None
        )

    def process(self, raw_targets: np.ndarray | None) -> np.ndarray | None:
        if raw_targets is None:
            return None

        raw = np.asarray(raw_targets, dtype=np.float32)
        if raw.shape != self._initial_targets.shape:
            raise ValueError(
                f"{self._side} {self._config.status_label} target shape mismatch: expected "
                f"{self._initial_targets.shape}, got {raw.shape}"
            )

        if self._config.retarget_output_mode == "absolute":
            target = raw
        elif self._config.neutral_calibration_samples > 0 and self._neutral is None:
            self._neutral_samples.append(raw.copy())
            if len(self._neutral_samples) >= self._config.neutral_calibration_samples:
                self._neutral = np.mean(np.stack(self._neutral_samples), axis=0).astype(
                    np.float32
                )
                print(
                    f"[{self._config.status_label}] {self._side} neutral calibrated with "
                    f"{len(self._neutral_samples)} sample(s)."
                )
            if self._last_target is not None:
                return self._last_target
            return self._initial_targets.copy()

        else:
            neutral = self._neutral if self._neutral is not None else np.zeros_like(raw)
            target = self._initial_targets + (raw - neutral)

        if self._config.clamp_to_joint_limits and self._joint_limits is not None:
            target = np.clip(target, self._joint_limits[:, 0], self._joint_limits[:, 1])

        if self._last_target is not None and self._config.smoothing_alpha < 1.0:
            alpha = self._config.smoothing_alpha
            target = self._last_target * (1.0 - alpha) + target * alpha

        self._last_target = target.astype(np.float32)
        if not self._announced:
            print(
                f"[{self._config.status_label}] {self._side} hand postprocess active: "
                f"mode={self._config.retarget_output_mode}, "
                f"neutral_samples={self._config.neutral_calibration_samples}, "
                f"clamp={self._config.clamp_to_joint_limits}, "
                f"smoothing_alpha={self._config.smoothing_alpha}."
            )
            self._announced = True
        return self._last_target


def wuji_hand_runtime_config(config: Mapping[str, Any]) -> WujiHandRuntimeConfig:
    profile = robot_profile_from_config(config)
    wuji_config_dir = None
    if profile.hand_wuji_config_dir is not None:
        wuji_config_dir = _resolve_config_relative_path(
            profile.hand_wuji_config_dir, config
        )
        if wuji_config_dir is None or not wuji_config_dir.is_dir():
            raise FileNotFoundError(
                f"Fixed {profile.status_label} Wuji retarget config directory does not exist: "
                f"{wuji_config_dir}"
            )

    return WujiHandRuntimeConfig(
        robot_variant=profile.variant,
        initial_joint_positions=dict(profile.initial_hand_joint_positions),
        left_joint_names=profile.left_hand_joint_names,
        right_joint_names=profile.right_hand_joint_names,
        axis_signs=dict(profile.axis_signs),
        retarget_backend=profile.hand_retarget_backend,
        status_label=profile.status_label,
        wuji_config_dir=wuji_config_dir,
    )


def avp_frame_binding_runtime_config(
    config: Mapping[str, Any],
) -> AvpFrameBindingRuntimeConfig:
    profile = robot_profile_from_config(config)
    robot_config = config.get("robot", {})
    if robot_config is None:
        robot_config = {}
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")

    binding_config = robot_config.get("avp_frame_binding", {})
    if binding_config is None:
        binding_config = {}
    if not isinstance(binding_config, Mapping):
        raise ValueError("Config field 'robot.avp_frame_binding' must be a mapping")
    calibration_window_s = float(binding_config.get("calibration_window_s", 3.0))
    if calibration_window_s < 0.0:
        raise ValueError(
            "Config field 'robot.avp_frame_binding.calibration_window_s' must be >= 0"
        )

    return AvpFrameBindingRuntimeConfig(
        status_label=profile.status_label,
        enabled=bool(binding_config.get("enabled", True)),
        calibration_window_s=calibration_window_s,
        robot_reference_body=str(
            binding_config.get("robot_reference_body", profile.reference_body)
        ),
        robot_reference_offset_pos=_float_tuple(
            binding_config.get("robot_reference_offset_pos"),
            name="robot.avp_frame_binding.robot_reference_offset_pos",
            length=3,
            default=profile.reference_offset_pos,
        ),
        robot_reference_offset_quat_xyzw=_float_tuple(
            binding_config.get("robot_reference_offset_quat_xyzw"),
            name="robot.avp_frame_binding.robot_reference_offset_quat_xyzw",
            length=4,
            default=profile.reference_offset_quat_xyzw,
        ),
        head_forward_axis_isaac=_float_tuple(
            binding_config.get("head_forward_axis_isaac"),
            name="robot.avp_frame_binding.head_forward_axis_isaac",
            length=3,
            default=(0.0, 1.0, 0.0),
        ),
    )


def openxr_to_isaac_position(
    position: Sequence[float], scale: float, offset_z: float
) -> np.ndarray:
    x, y, z = (float(v) for v in position)
    position_isaac = np.array([x, -z, y], dtype=np.float32) * float(scale)
    return position_isaac + np.array([0.0, 0.0, offset_z], dtype=np.float32)


def quat_xyzw_to_matrix(quat: Sequence[float]) -> np.ndarray:
    x, y, z, w = (float(v) for v in quat)
    norm = (x * x + y * y + z * z + w * w) ** 0.5
    if norm < 1.0e-8:
        return np.eye(3, dtype=np.float64)
    x /= norm
    y /= norm
    z /= norm
    w /= norm
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def matrix_to_quat_xyzw(matrix: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix, dtype=np.float64)
    trace = float(np.trace(m))
    if trace > 0.0:
        s = (trace + 1.0) ** 0.5 * 2.0
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = (1.0 + m[0, 0] - m[1, 1] - m[2, 2]) ** 0.5 * 2.0
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = (1.0 + m[1, 1] - m[0, 0] - m[2, 2]) ** 0.5 * 2.0
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = (1.0 + m[2, 2] - m[0, 0] - m[1, 1]) ** 0.5 * 2.0
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    quat = np.array([x, y, z, w], dtype=np.float32)
    quat_norm = np.linalg.norm(quat)
    if quat_norm > 1.0e-8:
        quat /= quat_norm
    return quat


def openxr_to_isaac_orientation(orientation_xyzw: Sequence[float]) -> np.ndarray:
    return matrix_to_quat_xyzw(openxr_to_isaac_rotation_matrix(orientation_xyzw))


def openxr_to_isaac_rotation_matrix(orientation_xyzw: Sequence[float]) -> np.ndarray:
    frame = np.array(
        [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]],
        dtype=np.float64,
    )
    return frame @ quat_xyzw_to_matrix(orientation_xyzw) @ frame.T


def normalize_quat_xyzw(quat: Sequence[float]) -> np.ndarray:
    out = np.asarray(quat, dtype=np.float32)
    norm = np.linalg.norm(out)
    if norm < 1.0e-8:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    return out / norm


def openxr_pose_to_isaac_pose(
    pose: Mapping[str, Any],
    *,
    scale: float,
    offset_z: float,
) -> tuple[np.ndarray, np.ndarray]:
    return (
        openxr_to_isaac_position(pose["position"], scale, offset_z),
        openxr_to_isaac_orientation(pose["orientation_xyzw"]),
    )


class AvpRobotFrameBinding:
    """Bind a startup head-hand AVP frame to the robot reference body."""

    def __init__(
        self,
        robot: Any,
        arm_ik_config: Any,
        config: AvpFrameBindingRuntimeConfig,
        *,
        pose_scale: float,
        pose_z_offset: float,
    ) -> None:
        _ = arm_ik_config
        self._robot = robot
        self._config = config
        self._pose_scale = float(pose_scale)
        self._pose_z_offset = float(pose_z_offset)
        self._reference_body_id = _find_single_body_id(
            robot,
            config.robot_reference_body,
            "AVP robot reference body",
        )
        self._reference_offset_pos = np.asarray(
            config.robot_reference_offset_pos, dtype=np.float64
        )
        self._reference_offset_rot = quat_xyzw_to_matrix(
            config.robot_reference_offset_quat_xyzw
        )
        self._head_forward_axis = _unit_vector(config.head_forward_axis_isaac)
        if self._head_forward_axis is None:
            raise ValueError(
                "Config field 'robot.avp_frame_binding.head_forward_axis_isaac' "
                "must be non-zero"
            )
        self._state: _AvpHeadHandBindingState | None = None
        self._pending_calibration: _AvpPendingHeadHandCalibration | None = None
        self._waiting_announced = False
        self._runtime_frame_rot: np.ndarray | None = None
        self._latest_head_tilt_delta_rot = np.eye(3, dtype=np.float64)

    def update_calibration(self, sample: Mapping[str, Any]) -> None:
        if not self._config.enabled or self._state is not None:
            return

        timestamp_s = _sample_timestamp_s(sample)
        pending = self._pending_calibration
        calibration = self._calibration_inputs(sample)
        if pending is None and calibration is None:
            self._maybe_log_waiting(sample)
            return

        if pending is None:
            pending = _AvpPendingHeadHandCalibration(
                start_timestamp_s=timestamp_s,
                last_timestamp_s=timestamp_s,
            )
            self._pending_calibration = pending
            print(
                f"[{self._config.status_label}] collecting AVP head-hand calibration samples "
                f"frame={int(sample.get('frame_count', 0))} "
                f"window_s={self._config.calibration_window_s:.2f}.",
                flush=True,
            )

        if calibration is not None:
            head_pos, head_rot, left_pos, right_pos = calibration
            pending.append(
                timestamp_s=timestamp_s,
                head_pos=head_pos,
                head_rot=head_rot,
                left_pos=left_pos,
                right_pos=right_pos,
            )

        elapsed_s = max(0.0, timestamp_s - pending.start_timestamp_s)
        if elapsed_s < self._config.calibration_window_s:
            return

        if pending.sample_count <= 0:
            self._pending_calibration = None
            self._waiting_announced = False
            self._maybe_log_waiting(
                sample,
                reason=(
                    "calibration window elapsed without valid head/hand samples "
                    f"elapsed_s={elapsed_s:.3f}"
                ),
            )
            return

        averaged_head_pos = pending.head_pos_sum / float(pending.sample_count)
        averaged_head_rot = _average_rotation_matrix(pending.head_rot_sum)
        averaged_left_pos = pending.left_pos_sum / float(pending.sample_count)
        averaged_right_pos = pending.right_pos_sum / float(pending.sample_count)
        if averaged_head_rot is None:
            self._pending_calibration = None
            self._waiting_announced = False
            self._maybe_log_waiting(
                sample,
                reason=(
                    "averaged head rotation was degenerate "
                    f"samples={pending.sample_count} elapsed_s={elapsed_s:.3f}"
                ),
            )
            return

        frame_rot = _head_hand_frame_rotation(
            head_rot=averaged_head_rot,
            left_pos=averaged_left_pos,
            right_pos=averaged_right_pos,
            head_forward_axis=self._head_forward_axis,
        )
        if frame_rot is None:
            wrist_delta = averaged_left_pos - averaged_right_pos
            self._pending_calibration = None
            self._waiting_announced = False
            self._maybe_log_waiting(
                sample,
                reason=(
                    "degenerate averaged head/hand axes "
                    f"samples={pending.sample_count} elapsed_s={elapsed_s:.3f} "
                    f"head={np.round(averaged_head_pos, 4).tolist()} "
                    f"left={np.round(averaged_left_pos, 4).tolist()} "
                    f"right={np.round(averaged_right_pos, 4).tolist()} "
                    f"left_right_norm={float(np.linalg.norm(wrist_delta)):.6f}"
                ),
            )
            return

        self._state = _AvpHeadHandBindingState(
            origin_pos=averaged_head_pos,
            frame_rot=frame_rot,
            head_rot=averaged_head_rot,
        )
        self._runtime_frame_rot = frame_rot.copy()
        self._latest_head_yaw_delta_rad = 0.0
        self._latest_head_tilt_delta_rot = np.eye(3, dtype=np.float64)
        self._pending_calibration = None
        self._announce_calibration(
            sample,
            averaged_head_pos,
            frame_rot,
            elapsed_s=elapsed_s,
            sample_count=pending.sample_count,
        )

    def reset_calibration(self) -> None:
        self._state = None
        self._pending_calibration = None
        self._waiting_announced = False
        self._runtime_frame_rot = None
        self._latest_head_tilt_delta_rot = np.eye(3, dtype=np.float64)
        print(
            f"[{self._config.status_label}] AVP head-hand frame calibration cleared; "
            "waiting for fresh calibration.",
            flush=True,
        )

    def update_runtime_state(self, sample: Mapping[str, Any]) -> None:
        state = self._state
        if not self._config.enabled or state is None:
            self._runtime_frame_rot = None
            self._latest_head_tilt_delta_rot = np.eye(3, dtype=np.float64)
            return

        if self._runtime_frame_rot is None:
            self._runtime_frame_rot = state.frame_rot

        head_pose = sample.get("head_pose")
        if head_pose is None:
            return

        current_head_rot = openxr_to_isaac_rotation_matrix(
            head_pose["orientation_xyzw"]
        )
        head_tilt_delta_rot = _head_tilt_delta_rotation(
            calibration_head_rot=state.head_rot,
            current_head_rot=current_head_rot,
            head_forward_axis=self._head_forward_axis,
        )
        if head_tilt_delta_rot is not None:
            self._latest_head_tilt_delta_rot = head_tilt_delta_rot

        self._runtime_frame_rot = state.frame_rot

    @property
    def calibrated(self) -> bool:
        return self._state is not None

    def latest_head_tilt_delta_rot(self) -> np.ndarray:
        return np.array(self._latest_head_tilt_delta_rot, copy=True)

    def transform_pose(
        self,
        side: str,
        pose: Mapping[str, Any],
    ) -> tuple[np.ndarray, np.ndarray] | None:
        raw_pos, raw_quat = openxr_pose_to_isaac_pose(
            pose,
            scale=self._pose_scale,
            offset_z=self._pose_z_offset,
        )
        if not self._config.enabled:
            return raw_pos, raw_quat

        state = self._state
        if state is None:
            return None

        frame_rot = self._runtime_frame_rot
        if frame_rot is None:
            frame_rot = state.frame_rot
        raw_rot = quat_xyzw_to_matrix(raw_quat)
        local_pos = frame_rot.T @ (
            np.asarray(raw_pos, dtype=np.float64) - state.origin_pos
        )
        local_rot = frame_rot.T @ raw_rot
        reference_pos, reference_rot = self._current_reference_world_pose()
        target_pos = reference_pos + reference_rot @ local_pos
        target_rot = reference_rot @ local_rot
        return target_pos.astype(np.float32), matrix_to_quat_xyzw(target_rot)

    def _current_reference_world_pose(self) -> tuple[np.ndarray, np.ndarray]:
        body_pos, body_rot = _body_pose_np(self._robot, self._reference_body_id)
        return (
            body_pos + body_rot @ self._reference_offset_pos,
            body_rot @ self._reference_offset_rot,
        )

    def _calibration_inputs(
        self, sample: Mapping[str, Any]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
        head_pose = sample.get("head_pose")
        ee_poses = sample.get("ee_poses", {})
        left_pose = ee_poses.get("left") if isinstance(ee_poses, Mapping) else None
        right_pose = ee_poses.get("right") if isinstance(ee_poses, Mapping) else None
        if head_pose is None or left_pose is None or right_pose is None:
            return None

        head_pos, head_quat = openxr_pose_to_isaac_pose(
            head_pose,
            scale=self._pose_scale,
            offset_z=self._pose_z_offset,
        )
        left_pos, _left_quat = openxr_pose_to_isaac_pose(
            left_pose,
            scale=self._pose_scale,
            offset_z=self._pose_z_offset,
        )
        right_pos, _right_quat = openxr_pose_to_isaac_pose(
            right_pose,
            scale=self._pose_scale,
            offset_z=self._pose_z_offset,
        )
        return (
            np.asarray(head_pos, dtype=np.float64),
            quat_xyzw_to_matrix(head_quat),
            np.asarray(left_pos, dtype=np.float64),
            np.asarray(right_pos, dtype=np.float64),
        )

    def _maybe_log_waiting(
        self, sample: Mapping[str, Any], *, reason: str | None = None
    ) -> None:
        if self._waiting_announced:
            return
        frame_count = int(sample.get("frame_count", 0))
        head_ready = sample.get("head_pose") is not None
        ee_poses = sample.get("ee_poses", {})
        left_ready = isinstance(ee_poses, Mapping) and ee_poses.get("left") is not None
        right_ready = (
            isinstance(ee_poses, Mapping) and ee_poses.get("right") is not None
        )
        detail = f" reason={reason}" if reason else ""
        print(
            f"[{self._config.status_label}] waiting for AVP head-hand frame calibration "
            f"frame={frame_count} head={head_ready} left={left_ready} "
            f"right={right_ready}{detail}",
            flush=True,
        )
        self._waiting_announced = True

    def _announce_calibration(
        self,
        sample: Mapping[str, Any],
        origin_pos: np.ndarray,
        frame_rot: np.ndarray,
        *,
        elapsed_s: float,
        sample_count: int,
    ) -> None:
        reference_body_pos, _reference_body_rot = _body_pose_np(
            self._robot, self._reference_body_id
        )
        reference_pos, _reference_rot = self._current_reference_world_pose()
        print(
            f"[{self._config.status_label}] AVP head-hand frame calibrated "
            f"frame={int(sample.get('frame_count', 0))} "
            f"elapsed_s={elapsed_s:.3f} samples={sample_count} "
            f"origin_isaac={origin_pos.tolist()} "
            f"x={frame_rot[:, 0].tolist()} y={frame_rot[:, 1].tolist()} "
            f"z={frame_rot[:, 2].tolist()} "
            f"robot_reference_body={self._config.robot_reference_body!r} "
            f"robot_reference_body_pos={reference_body_pos.astype(np.float32).tolist()} "
            f"robot_reference_pos={reference_pos.astype(np.float32).tolist()}",
            flush=True,
        )


class WujiHandTargetBackend:
    """Official Wuji retargeting from MANUS/OpenXR skeletons."""

    def __init__(self, config: WujiHandRuntimeConfig) -> None:
        self._config = config
        self._retargeter: Any | None = None
        self._announced = False
        self._waiting_announced = False

    def _ensure_retargeter(self) -> None:
        if self._retargeter is not None:
            return
        if self._config.retarget_backend != "official_wuji":
            raise ValueError(
                f"Unsupported hand retarget backend: {self._config.retarget_backend!r}"
            )

        from .retargeting import WujiOfficialManusHandRetargeter

        self._retargeter = WujiOfficialManusHandRetargeter(
            config_dir=self._config.wuji_config_dir
        )
        self._retargeter._ensure_retargeters()
        if not self._announced:
            print(
                f"[{self._config.status_label}] using hand retarget backend: "
                f"{self._config.retarget_backend} "
                f"(left_joints={len(self._retargeter.left_joint_names or ())}, "
                f"right_joints={len(self._retargeter.right_joint_names or ())}, "
                f"config={self._config.wuji_config_dir})."
            )
            self._announced = True

    @staticmethod
    def _to_numpy(values: Any) -> np.ndarray:
        if hasattr(values, "detach") and hasattr(values, "cpu"):
            values = values.detach().cpu().numpy()
        return np.asarray(values, dtype=np.float32).reshape(-1)

    def targets(
        self,
        sample: Mapping[str, Any],
    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        left_skeleton = _wuji_skeleton21_from_openxr(sample, "left")
        right_skeleton = _wuji_skeleton21_from_openxr(sample, "right")

        if left_skeleton is None and right_skeleton is None:
            if not self._waiting_announced:
                print(
                    f"[{self._config.status_label}] waiting for MANUS hand skeletons; "
                    "arm EE teleop remains independent.",
                    flush=True,
                )
                self._waiting_announced = True
            return None, None

        self._ensure_retargeter()
        self._waiting_announced = False
        frame_index = int(sample.get("frame_count", 0))
        left_targets = None
        if left_skeleton is not None:
            left_positions, left_joint_names = self._retargeter.retarget_manus_skeleton(
                "left",
                left_skeleton,
                frame_index=frame_index,
                device=None,
            )
            left_targets = _ordered_named_targets(
                values=self._to_numpy(left_positions),
                source_names=left_joint_names,
                target_names=self._config.left_joint_names,
                side="left",
                label=self._config.retarget_backend,
                axis_signs=self._config.axis_signs,
                status_label=self._config.status_label,
            )

        right_targets = None
        if right_skeleton is not None:
            right_positions, right_joint_names = (
                self._retargeter.retarget_manus_skeleton(
                    "right",
                    right_skeleton,
                    frame_index=frame_index,
                    device=None,
                )
            )
            right_targets = _ordered_named_targets(
                values=self._to_numpy(right_positions),
                source_names=right_joint_names,
                target_names=self._config.right_joint_names,
                side="right",
                label=self._config.retarget_backend,
                axis_signs=self._config.axis_signs,
                status_label=self._config.status_label,
            )
        return left_targets, right_targets


def _resolve_config_relative_path(value: Any, config: Mapping[str, Any]) -> Path | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    default_config_dir = example_root() / "config"
    base_dir = Path(str(config.get("_config_dir", default_config_dir))).expanduser()
    return (base_dir / path).resolve()


def _float_tuple(
    values: Any,
    *,
    name: str,
    length: int,
    default: Sequence[float],
) -> tuple[float, ...]:
    raw = default if values is None else values
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError(f"Config field {name!r} must be a {length}-element sequence")
    if len(raw) != length:
        raise ValueError(f"Config field {name!r} must contain exactly {length} values")
    return tuple(float(value) for value in raw)


def _unit_vector(values: Sequence[float] | np.ndarray) -> np.ndarray | None:
    vector = np.asarray(values, dtype=np.float64).reshape(-1)
    if vector.size != 3:
        return None
    norm = np.linalg.norm(vector)
    if norm < 1.0e-8:
        return None
    return vector / norm


def _sample_timestamp_s(sample: Mapping[str, Any]) -> float:
    timestamp = sample.get("timestamp_s")
    if timestamp is None:
        return time.monotonic()
    return float(timestamp)


def _average_rotation_matrix(matrix_sum: np.ndarray) -> np.ndarray | None:
    matrix = np.asarray(matrix_sum, dtype=np.float64)
    if matrix.shape != (3, 3) or np.linalg.norm(matrix) < 1.0e-8:
        return None

    u, _s, vt = np.linalg.svd(matrix)

    rotation = u @ vt
    if np.linalg.det(rotation) < 0.0:
        u[:, -1] *= -1.0
        rotation = u @ vt
    return rotation


def _head_hand_frame_rotation(
    *,
    head_rot: np.ndarray,
    left_pos: np.ndarray,
    right_pos: np.ndarray,
    head_forward_axis: np.ndarray,
) -> np.ndarray | None:
    x_axis = _unit_vector(head_rot @ head_forward_axis)
    if x_axis is None:
        return None

    y_axis_raw = _unit_vector(left_pos - right_pos)
    if y_axis_raw is None:
        return None
    else:
        z_axis = _unit_vector(np.cross(x_axis, y_axis_raw))
        if z_axis is None:
            return None
        else:
            y_axis = _unit_vector(np.cross(z_axis, x_axis))
    if y_axis is None:
        return None

    z_axis = _unit_vector(np.cross(x_axis, y_axis))
    if z_axis is None:
        return None
    frame_rot = np.column_stack((x_axis, y_axis, z_axis))
    if np.linalg.det(frame_rot) < 0.0:
        frame_rot[:, 2] *= -1.0
    return frame_rot


def _head_tilt_delta_rotation(
    *,
    calibration_head_rot: np.ndarray,
    current_head_rot: np.ndarray,
    head_forward_axis: np.ndarray,
) -> np.ndarray | None:
    calibration_tilt = _yaw_removed_rotation(
        rotation=calibration_head_rot,
        forward_axis=head_forward_axis,
    )
    current_tilt = _yaw_removed_rotation(
        rotation=current_head_rot,
        forward_axis=head_forward_axis,
    )
    if calibration_tilt is None or current_tilt is None:
        return None
    tilt_delta = current_tilt @ calibration_tilt.T
    if np.linalg.det(tilt_delta) < 0.0:
        return None
    return tilt_delta


def _yaw_removed_rotation(
    *,
    rotation: np.ndarray,
    forward_axis: np.ndarray,
) -> np.ndarray | None:
    yaw_rot = _world_z_yaw_rotation_from_forward(
        rotation=rotation,
        forward_axis=forward_axis,
    )
    if yaw_rot is None:
        return None
    return yaw_rot.T @ rotation


def _world_z_yaw_rotation_from_forward(
    *,
    rotation: np.ndarray,
    forward_axis: np.ndarray,
) -> np.ndarray | None:
    forward_local = _unit_vector(forward_axis)
    if forward_local is None:
        return None

    reference_forward = _unit_vector(
        np.asarray([forward_local[0], forward_local[1], 0.0], dtype=np.float64)
    )
    current_forward = _unit_vector(rotation @ forward_local)
    if reference_forward is None or current_forward is None:
        return None
    projected_forward = _unit_vector(
        np.asarray([current_forward[0], current_forward[1], 0.0], dtype=np.float64)
    )
    if projected_forward is None:
        return None

    yaw_rad = float(
        np.arctan2(
            reference_forward[0] * projected_forward[1]
            - reference_forward[1] * projected_forward[0],
            reference_forward[0] * projected_forward[0]
            + reference_forward[1] * projected_forward[1],
        )
    )
    cos_yaw = float(np.cos(yaw_rad))
    sin_yaw = float(np.sin(yaw_rad))
    return np.array(
        [
            [cos_yaw, -sin_yaw, 0.0],
            [sin_yaw, cos_yaw, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def _find_single_body_id(robot: Any, body_name: str, label: str) -> int:
    body_ids, body_names = robot.find_bodies(body_name)
    if len(body_ids) == 1:
        return int(body_ids[0])

    available = list(getattr(robot.data, "body_names", []) or [])
    preview = available[:40]
    raise RuntimeError(
        f"Expected one {label} match for {body_name!r}; got {len(body_ids)}: "
        f"{body_names}. Available body names first entries: {preview}"
    )


def as_torch(value: Any) -> Any:
    """Return a torch tensor from Isaac Lab buffers or Warp arrays."""
    import torch

    if isinstance(value, torch.Tensor):
        return value
    import warp as wp

    return wp.to_torch(value)


def _first_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        return value.detach().cpu().numpy()

    return as_torch(value).detach().cpu().numpy()


def _body_pose_np(robot: Any, body_id: int) -> tuple[np.ndarray, np.ndarray]:
    body_pos = np.asarray(
        _first_numpy(robot.data.body_pos_w)[0, body_id], dtype=np.float64
    )
    body_quat = np.asarray(
        _first_numpy(robot.data.body_quat_w)[0, body_id], dtype=np.float64
    )
    return body_pos, quat_xyzw_to_matrix(body_quat)


def _ordered_named_targets(
    *,
    values: Any,
    source_names: Sequence[str] | None,
    target_names: Sequence[str],
    side: str,
    label: str,
    axis_signs: Mapping[str, float] | None = None,
    status_label: str = "teleop",
) -> np.ndarray | None:
    if values is None:
        return None

    values_array = np.asarray(values, dtype=np.float32).reshape(-1)
    if source_names is None:
        raise RuntimeError(
            f"[{status_label}] retarget backend={label} side={side} did not "
            "provide joint names"
        )

    values_by_name = {
        str(name): float(values_array[i])
        for i, name in enumerate(source_names)
        if i < values_array.size
    }
    resolved_values: dict[str, float] = {}
    used_source_names: set[str] = set()
    side_prefix = f"{side}_"
    for name in target_names:
        source_name = name
        if source_name not in values_by_name and name.startswith(side_prefix):
            source_name = name.removeprefix(side_prefix)
        if source_name in values_by_name:
            resolved_values[name] = values_by_name[source_name]
            used_source_names.add(source_name)

    missing = [name for name in target_names if name not in resolved_values]
    if missing:
        extra = [name for name in values_by_name if name not in used_source_names]
        raise RuntimeError(
            f"[{status_label}] retarget joint-name mismatch "
            f"backend={label} side={side} missing={missing[:8]} "
            f"total_missing={len(missing)} extra={extra[:8]} total_extra={len(extra)}"
        )

    ordered = np.zeros(len(target_names), dtype=np.float32)
    sign_map = axis_signs or {}
    for i, name in enumerate(target_names):
        ordered[i] = resolved_values[name] * sign_map.get(name, 1.0)
    return ordered


def _wuji_skeleton21_from_openxr(
    sample: Mapping[str, Any], side: str
) -> np.ndarray | None:
    skeletons = sample.get("hand_skeletons", {})
    skeleton = skeletons.get(side) if isinstance(skeletons, Mapping) else None
    if not isinstance(skeleton, Mapping):
        return None

    joint_names = skeleton.get("joint_names")
    positions = skeleton.get("positions")
    if not isinstance(joint_names, Sequence) or positions is None:
        return None

    positions_array = np.asarray(positions, dtype=np.float32)
    if positions_array.ndim != 2 or positions_array.shape[1] != 3:
        return None

    valid_values = skeleton.get("valid")
    valid_array = (
        np.ones(positions_array.shape[0], dtype=bool)
        if valid_values is None
        else np.asarray(valid_values, dtype=bool).reshape(-1)
    )
    name_to_index = {str(name): index for index, name in enumerate(joint_names)}

    out = np.zeros((len(WUJI_SKELETON21_OPENXR_NAMES), 3), dtype=np.float32)
    missing: list[str] = []
    for out_index, name in enumerate(WUJI_SKELETON21_OPENXR_NAMES):
        source_index = name_to_index.get(name)
        if (
            source_index is None
            or source_index >= positions_array.shape[0]
            or source_index >= valid_array.size
            or not bool(valid_array[source_index])
        ):
            missing.append(name)
            continue
        out[out_index] = positions_array[source_index]

    if missing:
        return None

    if not np.all(np.isfinite(out)):
        return None
    return out
