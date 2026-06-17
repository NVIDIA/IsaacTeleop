# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Live 3D visualizer for the G1-Wuji AVP + MANUS teleop stream.

Run from a shell that has sourced the CloudXR environment, for example:

    source ~/.cloudxr/run/cloudxr.env
    python examples/g1_wuji_teleop/scripts/g1_wuji_teleop_visualizer.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

if not os.environ.get("MPLBACKEND"):
    matplotlib.use("TkAgg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

from ..devices.avp_manus_stream import TeleopMain
from ..paths import (
    default_config_path as app_default_config_path,
    ensure_import_paths,
)


SIDE_COLORS = {
    "left": "dodgerblue",
    "right": "tomato",
}

HEAD_COLOR = "black"
HEAD_AXIS_LENGTH = 0.1
HEAD_FORWARD_AXIS_ISAAC = np.asarray([0.0, 1.0, 0.0], dtype=np.float64)
OPENXR_TO_ISAAC_FRAME = np.asarray(
    [
        [1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0],
        [0.0, 1.0, 0.0],
    ],
    dtype=np.float64,
)

VIEW_PRESETS = (
    ("forward +X", 0.0, 180.0),
    ("iso", 24.0, -58.0),
    ("left +Y", 0.0, -90.0),
    ("right -Y", 0.0, 90.0),
    ("top", 90.0, -90.0),
    ("back -X", 0.0, 0.0),
)

DISPLAY_FRAME = np.eye(3, dtype=np.float64)


@dataclass(frozen=True)
class VisualFrameState:
    origin_pos: np.ndarray
    frame_rot: np.ndarray


OPENXR_HAND_BONES = (
    ("wrist", "palm"),
    ("wrist", "thumb_metacarpal"),
    ("thumb_metacarpal", "thumb_proximal"),
    ("thumb_proximal", "thumb_distal"),
    ("thumb_distal", "thumb_tip"),
    ("wrist", "index_metacarpal"),
    ("index_metacarpal", "index_proximal"),
    ("index_proximal", "index_intermediate"),
    ("index_intermediate", "index_distal"),
    ("index_distal", "index_tip"),
    ("wrist", "middle_metacarpal"),
    ("middle_metacarpal", "middle_proximal"),
    ("middle_proximal", "middle_intermediate"),
    ("middle_intermediate", "middle_distal"),
    ("middle_distal", "middle_tip"),
    ("wrist", "ring_metacarpal"),
    ("ring_metacarpal", "ring_proximal"),
    ("ring_proximal", "ring_intermediate"),
    ("ring_intermediate", "ring_distal"),
    ("ring_distal", "ring_tip"),
    ("wrist", "little_metacarpal"),
    ("little_metacarpal", "little_proximal"),
    ("little_proximal", "little_intermediate"),
    ("little_intermediate", "little_distal"),
    ("little_distal", "little_tip"),
)

ROBOT_FINGER_KEYS = {
    "index": ("index_proximal", "index_distal"),
    "middle": ("middle_proximal", "middle_distal"),
    "ring": ("ring_proximal", "ring_distal"),
    "pinky": ("pinky_proximal", "pinky_distal"),
    "thumb": ("thumb_proximal_yaw", "thumb_proximal_pitch"),
}


def default_config_path() -> Path:
    return app_default_config_path()


def require_cloudxr_environment() -> None:
    if os.environ.get("ISAAC_TELEOP_DISABLE_CXR_ENV_CHECKS"):
        return

    missing = [
        name
        for name in ("NV_CXR_RUNTIME_DIR", "XR_RUNTIME_JSON")
        if not os.environ.get(name)
    ]
    if not missing:
        return

    env_path = Path.home() / ".cloudxr" / "run" / "cloudxr.env"
    hint = (
        "CloudXR/OpenXR environment is not loaded. Run this in the same shell "
        "before starting the visualizer:\n\n"
        f"  source {env_path}\n"
        "  python examples/g1_wuji_teleop/scripts/g1_wuji_teleop_visualizer.py "
        "--config examples/g1_wuji_teleop/config/avp_manus.yml\n"
    )
    if not env_path.exists():
        hint += "\nIf that file is missing, start CloudXR first:\n\n"
        hint += "  python -m isaacteleop.cloudxr\n"
    raise RuntimeError(f"Missing environment variables: {', '.join(missing)}\n{hint}")


def quat_xyzw_to_rotmat(quat_xyzw: Sequence[float]) -> np.ndarray:
    qx, qy, qz, qw = [float(v) for v in quat_xyzw]
    norm = np.linalg.norm([qx, qy, qz, qw])
    if norm <= 1e-8:
        return np.eye(3, dtype=np.float64)
    qx, qy, qz, qw = [value / norm for value in (qx, qy, qz, qw)]
    return np.asarray(
        [
            [
                1.0 - 2.0 * (qy * qy + qz * qz),
                2.0 * (qx * qy - qw * qz),
                2.0 * (qx * qz + qw * qy),
            ],
            [
                2.0 * (qx * qy + qw * qz),
                1.0 - 2.0 * (qx * qx + qz * qz),
                2.0 * (qy * qz - qw * qx),
            ],
            [
                2.0 * (qx * qz - qw * qy),
                2.0 * (qy * qz + qw * qx),
                1.0 - 2.0 * (qx * qx + qy * qy),
            ],
        ],
        dtype=np.float64,
    )


def pose_to_matrix(pose: Mapping[str, Any]) -> np.ndarray:
    mat = np.eye(4, dtype=np.float64)
    mat[:3, :3] = quat_xyzw_to_rotmat(pose["orientation_xyzw"])
    mat[:3, 3] = np.asarray(pose["position"], dtype=np.float64)
    return mat


def openxr_pose_to_isaac_matrix(pose: Mapping[str, Any]) -> np.ndarray:
    raw = pose_to_matrix(pose)
    mat = np.eye(4, dtype=np.float64)
    mat[:3, :3] = OPENXR_TO_ISAAC_FRAME @ raw[:3, :3] @ OPENXR_TO_ISAAC_FRAME.T
    mat[:3, 3] = OPENXR_TO_ISAAC_FRAME @ raw[:3, 3]
    return mat


def visual_frame_state_from_sample(
    sample: Mapping[str, Any],
) -> VisualFrameState | None:
    head_pose = sample.get("head_pose")
    ee_poses = sample.get("ee_poses", {})
    left_pose = ee_poses.get("left") if isinstance(ee_poses, Mapping) else None
    right_pose = ee_poses.get("right") if isinstance(ee_poses, Mapping) else None
    if head_pose is None or left_pose is None or right_pose is None:
        return None

    head_mat = openxr_pose_to_isaac_matrix(head_pose)
    left_mat = openxr_pose_to_isaac_matrix(left_pose)
    right_mat = openxr_pose_to_isaac_matrix(right_pose)

    x_axis = normalize_vector(head_mat[:3, :3] @ HEAD_FORWARD_AXIS_ISAAC)
    y_axis_raw = normalize_vector(left_mat[:3, 3] - right_mat[:3, 3])
    if x_axis is None:
        return None

    if y_axis_raw is None:
        y_axis = fallback_lateral_axis(x_axis)
    else:
        z_axis = normalize_vector(np.cross(x_axis, y_axis_raw))
        if z_axis is None:
            y_axis = fallback_lateral_axis(x_axis)
        else:
            y_axis = normalize_vector(np.cross(z_axis, x_axis))
    if y_axis is None:
        return None

    z_axis = normalize_vector(np.cross(x_axis, y_axis))
    if z_axis is None:
        return None
    frame_rot = np.column_stack((x_axis, y_axis, z_axis))
    if np.linalg.det(frame_rot) < 0.0:
        frame_rot[:, 2] *= -1.0
    return VisualFrameState(
        origin_pos=head_mat[:3, 3].copy(),
        frame_rot=frame_rot,
    )


def fallback_lateral_axis(x_axis: np.ndarray) -> np.ndarray | None:
    # Early tracker frames can report coincident wrists; do not block visualizer startup.
    up_hint = np.asarray([0.0, 0.0, 1.0], dtype=np.float64)
    if abs(float(np.dot(x_axis, up_hint))) > 0.95:
        up_hint = np.asarray([0.0, 1.0, 0.0], dtype=np.float64)
    return normalize_vector(np.cross(up_hint, x_axis))


def pose_to_visual_frame_matrix(
    pose: Mapping[str, Any],
    state: VisualFrameState,
) -> np.ndarray:
    raw_mat = openxr_pose_to_isaac_matrix(pose)
    mat = np.eye(4, dtype=np.float64)
    mat[:3, :3] = state.frame_rot.T @ raw_mat[:3, :3]
    mat[:3, 3] = state.frame_rot.T @ (raw_mat[:3, 3] - state.origin_pos)
    return mat


def skeleton_to_visual_frame(
    skeleton: Mapping[str, Any] | None,
    state: VisualFrameState,
) -> dict[str, Any] | None:
    if skeleton is None:
        return None
    positions = np.asarray(skeleton.get("positions", []), dtype=np.float64)
    if positions.ndim != 2 or positions.shape[1] != 3:
        return None

    positions_isaac = positions @ OPENXR_TO_ISAAC_FRAME.T
    local_positions = (positions_isaac - state.origin_pos) @ state.frame_rot
    transformed = dict(skeleton)
    transformed["positions"] = [
        [float(coord) for coord in position] for position in local_positions
    ]
    return transformed


def transform_points(points: np.ndarray, display_frame: np.ndarray) -> np.ndarray:
    return np.asarray(points, dtype=np.float64) @ display_frame.T


def transform_vector(vector: np.ndarray, display_frame: np.ndarray) -> np.ndarray:
    return display_frame @ np.asarray(vector, dtype=np.float64)


def transform_rotation(rot: np.ndarray, display_frame: np.ndarray) -> np.ndarray:
    return display_frame @ np.asarray(rot, dtype=np.float64)


def transform_pose_matrix(mat: np.ndarray, display_frame: np.ndarray) -> np.ndarray:
    transformed = np.eye(4, dtype=np.float64)
    transformed[:3, :3] = transform_rotation(mat[:3, :3], display_frame)
    transformed[:3, 3] = transform_vector(mat[:3, 3], display_frame)
    return transformed


def draw_pose_axes(
    ax,
    position: np.ndarray,
    rot: np.ndarray,
    *,
    length: float,
    alpha: float = 0.9,
) -> None:
    axis_colors = ("red", "green", "blue")
    for axis_index, color in enumerate(axis_colors):
        direction = rot[:, axis_index] * length
        ax.quiver(
            position[0],
            position[1],
            position[2],
            direction[0],
            direction[1],
            direction[2],
            color=color,
            arrow_length_ratio=0.25,
            linewidth=2.0,
            alpha=alpha,
        )


def draw_world_axes(
    ax,
    *,
    display_frame: np.ndarray,
    length: float,
    label: str,
) -> None:
    origin = np.zeros(3, dtype=np.float64)
    draw_pose_axes(
        ax,
        origin,
        transform_rotation(np.eye(3), display_frame),
        length=length,
        alpha=0.75,
    )
    ax.scatter(
        0.0,
        0.0,
        0.0,
        color="black",
        marker="+",
        s=90,
        alpha=0.65,
        label=label,
    )
    labels = (
        ("+X forward", np.asarray([length, 0.0, 0.0]), "red"),
        ("+Y left", np.asarray([0.0, length, 0.0]), "green"),
        ("+Z up", np.asarray([0.0, 0.0, length]), "blue"),
    )
    for text, point, color in labels:
        drawn = transform_vector(point, display_frame)
        ax.text(drawn[0], drawn[1], drawn[2], text, color=color, fontsize=9)


def draw_fixed_head_pose(
    ax,
    *,
    display_frame: np.ndarray,
) -> np.ndarray:
    # Keep this always-on so visualizer startup matches the teleop debug path.
    head_mat = transform_pose_matrix(np.eye(4, dtype=np.float64), display_frame)
    position = head_mat[:3, 3]
    rot = head_mat[:3, :3]
    ax.scatter(
        position[0],
        position[1],
        position[2],
        color=HEAD_COLOR,
        edgecolors="white",
        linewidths=0.8,
        marker="s",
        s=160,
        label="head fixed",
        zorder=11,
    )
    ax.text(
        position[0],
        position[1],
        position[2],
        "head",
        color=HEAD_COLOR,
        fontsize=9,
    )
    draw_pose_axes(
        ax,
        position,
        rot,
        length=HEAD_AXIS_LENGTH,
        alpha=0.95,
    )
    return position


def normalize_vector(vector: np.ndarray) -> np.ndarray | None:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-6:
        return None
    return vector / norm


def geometric_hand_frame(
    skeleton: Mapping[str, Any] | None,
    *,
    side: str,
) -> np.ndarray | None:
    if skeleton is None:
        return None

    joint_names = [str(name) for name in skeleton.get("joint_names", [])]
    positions = np.asarray(skeleton.get("positions", []), dtype=np.float64)
    valid = np.asarray(skeleton.get("valid", []), dtype=bool)
    if positions.ndim != 2 or positions.shape[1] != 3:
        return None
    if valid.ndim != 1 or positions.shape[0] != valid.shape[0]:
        return None

    name_to_index = {name: index for index, name in enumerate(joint_names)}

    def joint(name: str) -> np.ndarray | None:
        index = name_to_index.get(name)
        if index is None or not valid[index]:
            return None
        return positions[index]

    def first_valid(*names: str) -> np.ndarray | None:
        for name in names:
            point = joint(name)
            if point is not None:
                return point
        return None

    wrist = joint("wrist")
    palm = joint("palm")
    index = first_valid("index_metacarpal", "index_proximal")
    middle = first_valid("middle_metacarpal", "middle_proximal")
    little = first_valid("little_metacarpal", "little_proximal")
    if wrist is None or middle is None:
        return None

    forward_target = palm if palm is not None else middle
    forward = normalize_vector(forward_target - wrist)
    if forward is None:
        return None

    if index is not None and little is not None:
        lateral_raw = little - index if side == "left" else index - little
    elif index is not None:
        lateral_raw = index - middle
    elif little is not None:
        lateral_raw = middle - little
    else:
        return None

    lateral = lateral_raw - np.dot(lateral_raw, forward) * forward
    x_axis = normalize_vector(lateral)
    if x_axis is None:
        return None

    y_axis = normalize_vector(np.cross(forward, x_axis))
    if y_axis is None:
        return None
    z_axis = normalize_vector(np.cross(x_axis, y_axis))
    if z_axis is None:
        return None
    return np.column_stack((x_axis, y_axis, z_axis))


def skeleton_points(skeleton: Mapping[str, Any] | None) -> np.ndarray:
    if skeleton is None:
        return np.empty((0, 3), dtype=np.float64)
    positions = np.asarray(skeleton.get("positions", []), dtype=np.float64)
    valid = np.asarray(skeleton.get("valid", []), dtype=bool)
    if positions.ndim != 2 or positions.shape[1] != 3 or valid.ndim != 1:
        return np.empty((0, 3), dtype=np.float64)
    if positions.shape[0] != valid.shape[0]:
        return np.empty((0, 3), dtype=np.float64)
    return positions[valid]


def draw_openxr_skeleton(
    ax,
    skeleton: Mapping[str, Any],
    *,
    display_frame: np.ndarray,
    color: str,
    alpha: float,
) -> list[np.ndarray]:
    joint_names = [str(name) for name in skeleton.get("joint_names", [])]
    positions = np.asarray(skeleton.get("positions", []), dtype=np.float64)
    valid = np.asarray(skeleton.get("valid", []), dtype=bool)
    if positions.ndim != 2 or positions.shape[1] != 3:
        return []
    if valid.ndim != 1 or positions.shape[0] != valid.shape[0]:
        return []

    name_to_index = {name: index for index, name in enumerate(joint_names)}
    draw_positions = transform_points(positions, display_frame)
    drawn_points: list[np.ndarray] = []
    for joint_a, joint_b in OPENXR_HAND_BONES:
        index_a = name_to_index.get(joint_a)
        index_b = name_to_index.get(joint_b)
        if index_a is None or index_b is None:
            continue
        if not (valid[index_a] and valid[index_b]):
            continue
        point_a = draw_positions[index_a]
        point_b = draw_positions[index_b]
        ax.plot(
            [point_a[0], point_b[0]],
            [point_a[1], point_b[1]],
            [point_a[2], point_b[2]],
            color=color,
            linewidth=2.0,
            alpha=alpha,
        )
        drawn_points.extend([point_a, point_b])

    points = draw_positions[valid]
    if points.size:
        ax.scatter(
            points[:, 0],
            points[:, 1],
            points[:, 2],
            color=color,
            s=14,
            alpha=min(0.9, alpha + 0.1),
        )
        drawn_points.extend(list(points))
    return drawn_points


def joint_lookup(
    joint_names: Sequence[str],
    joint_positions: Sequence[float] | None,
    side: str,
) -> dict[str, float]:
    if joint_positions is None:
        return {}
    prefix = f"{side[0].upper()}_"
    lookup: dict[str, float] = {}
    for name, value in zip(joint_names, joint_positions):
        clean_name = str(name)
        if clean_name.startswith(prefix):
            clean_name = clean_name[len(prefix) :]
        if clean_name.endswith("_joint"):
            clean_name = clean_name[: -len("_joint")]
        lookup[clean_name] = float(value)
    return lookup


def fallback_finger_chain(
    *,
    lateral: float,
    base_forward: float,
    flex_a: float,
    flex_b: float,
    scale: float,
) -> np.ndarray:
    lengths = np.asarray([0.040, 0.030, 0.023], dtype=np.float64) * scale
    angles = np.asarray([0.15, flex_a, flex_a + flex_b], dtype=np.float64)
    points = [np.asarray([lateral, 0.0, base_forward], dtype=np.float64) * scale]
    current = points[0].copy()
    for length, angle in zip(lengths, angles):
        direction = np.asarray([0.0, -np.sin(angle), np.cos(angle)])
        current = current + direction * length
        points.append(current.copy())
    return np.asarray(points, dtype=np.float64)


def fallback_thumb_chain(
    *,
    side_sign: float,
    yaw: float,
    pitch: float,
    scale: float,
) -> np.ndarray:
    base = np.asarray([side_sign * 0.050, -0.005, 0.010], dtype=np.float64) * scale
    lengths = np.asarray([0.035, 0.027, 0.022], dtype=np.float64) * scale
    direction = np.asarray(
        [
            side_sign * (0.65 + 0.25 * np.sin(yaw)),
            -0.25 - 0.55 * np.sin(pitch),
            0.60 * np.cos(pitch),
        ],
        dtype=np.float64,
    )
    direction /= max(float(np.linalg.norm(direction)), 1e-8)
    points = [base]
    current = base.copy()
    for length in lengths:
        current = current + direction * length
        points.append(current.copy())
    return np.asarray(points, dtype=np.float64)


def draw_fallback_hand(
    ax,
    *,
    pose_mat: np.ndarray,
    joint_names: Sequence[str],
    joint_positions: Sequence[float] | None,
    side: str,
    color: str,
    display_frame: np.ndarray,
    scale: float,
) -> list[np.ndarray]:
    lookup = joint_lookup(joint_names, joint_positions, side)
    rot = pose_mat[:3, :3]
    origin = pose_mat[:3, 3]
    side_sign = -1.0 if side == "left" else 1.0
    local_chains = []

    finger_offsets = {
        "index": side_sign * 0.030,
        "middle": side_sign * 0.010,
        "ring": side_sign * -0.012,
        "pinky": side_sign * -0.032,
    }
    for finger, lateral in finger_offsets.items():
        flex_keys = ROBOT_FINGER_KEYS[finger]
        local_chains.append(
            fallback_finger_chain(
                lateral=lateral,
                base_forward=0.020,
                flex_a=lookup.get(flex_keys[0], 0.2),
                flex_b=lookup.get(flex_keys[1], 0.2),
                scale=scale,
            )
        )

    thumb_yaw, thumb_pitch = ROBOT_FINGER_KEYS["thumb"]
    local_chains.append(
        fallback_thumb_chain(
            side_sign=side_sign,
            yaw=lookup.get(thumb_yaw, 0.0),
            pitch=lookup.get(thumb_pitch, 0.2),
            scale=scale,
        )
    )

    palm = (
        np.asarray(
            [
                [0.0, 0.0, 0.0],
                [side_sign * 0.040, -0.004, 0.010],
                [side_sign * -0.040, -0.004, 0.010],
            ],
            dtype=np.float64,
        )
        * scale
    )
    world_palm = transform_points(origin + palm @ rot.T, display_frame)
    ax.plot(
        world_palm[:, 0],
        world_palm[:, 1],
        world_palm[:, 2],
        color=color,
        linewidth=1.4,
        alpha=0.55,
    )

    world_points: list[np.ndarray] = []
    for chain in local_chains:
        world_chain = transform_points(origin + chain @ rot.T, display_frame)
        ax.plot(
            world_chain[:, 0],
            world_chain[:, 1],
            world_chain[:, 2],
            color=color,
            linewidth=2.0,
            alpha=0.75,
        )
        ax.scatter(
            world_chain[:, 0],
            world_chain[:, 1],
            world_chain[:, 2],
            color=color,
            s=12,
            alpha=0.65,
        )
        world_points.extend(list(world_chain))
    world_points.extend(list(world_palm))
    return world_points


def set_equal_axes(ax, points: Sequence[np.ndarray], min_half_width: float) -> None:
    finite_points = [
        np.asarray(point, dtype=np.float64)
        for point in points
        if np.asarray(point).shape == (3,) and np.all(np.isfinite(point))
    ]
    if not finite_points:
        ax.set_xlim(-min_half_width, min_half_width)
        ax.set_ylim(-min_half_width, min_half_width)
        ax.set_zlim(-min_half_width, min_half_width)
        return

    pts = np.asarray(finite_points, dtype=np.float64)
    center = (pts.min(axis=0) + pts.max(axis=0)) * 0.5
    span = float((pts.max(axis=0) - pts.min(axis=0)).max())
    half_width = max(min_half_width, span * 0.65)
    ax.set_xlim(center[0] - half_width, center[0] + half_width)
    ax.set_ylim(center[1] - half_width, center[1] + half_width)
    ax.set_zlim(center[2] - half_width, center[2] + half_width)
    try:
        ax.set_box_aspect((1, 1, 1))
    except AttributeError:
        pass


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visualize AVP/MANUS teleop EE poses and hand skeletons."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="YAML config used by the G1-Wuji teleop app.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Visualization and teleop sampling rate.",
    )
    parser.add_argument(
        "--axis-limit",
        type=float,
        default=0.12,
        help="Minimum half-width of the 3D view, in meters.",
    )
    parser.add_argument(
        "--window-width",
        type=float,
        default=14.0,
        help="Matplotlib window width in inches.",
    )
    parser.add_argument(
        "--window-height",
        type=float,
        default=10.0,
        help="Matplotlib window height in inches.",
    )
    parser.add_argument(
        "--include-origin",
        action="store_true",
        help="Include the world origin in auto-scaling.",
    )
    parser.add_argument(
        "--world-axis-length",
        type=float,
        default=0.16,
        help="Length of the drawn calibrated head-hand coordinate axes in meters.",
    )
    parser.add_argument(
        "--trail",
        type=int,
        default=120,
        help="Number of EE trail points to keep per side. Use 0 to disable.",
    )
    parser.add_argument(
        "--arrow-length",
        type=float,
        default=0.08,
        help="EE orientation arrow length, in meters.",
    )
    parser.add_argument(
        "--ee-arrow-mode",
        choices=("hand", "pose"),
        default="hand",
        help=(
            "Arrow frame source: 'hand' derives axes from visible hand geometry; "
            "'pose' draws the calibrated EE quaternion."
        ),
    )
    parser.add_argument(
        "--fallback-hand-scale",
        type=float,
        default=1.0,
        help="Scale for the synthetic hand skeleton used when raw hand joints are absent.",
    )
    return parser.parse_args(sys.argv[1:] if argv is None else argv)


def main(argv: Sequence[str] | None = None) -> int:
    ensure_import_paths()
    args = parse_args(argv)
    require_cloudxr_environment()
    display_frame = DISPLAY_FRAME
    trails = {side: deque(maxlen=max(0, args.trail)) for side in SIDE_COLORS}
    fig = plt.figure(figsize=(args.window_width, args.window_height))
    ax = fig.add_subplot(111, projection="3d")
    start_s = time.monotonic()
    frames = 0
    last_print_s = 0.0
    latest_sample: dict[str, Any] | None = None
    visual_frame_state: VisualFrameState | None = None
    view_index = 0

    def apply_view() -> None:
        _name, elev, azim = VIEW_PRESETS[view_index]
        ax.view_init(elev=elev, azim=azim)

    def on_click(event) -> None:
        nonlocal view_index
        if event.inaxes is not ax:
            return
        view_index = (view_index + 1) % len(VIEW_PRESETS)
        apply_view()
        fig.canvas.draw_idle()
        print(f"view={VIEW_PRESETS[view_index][0]}", flush=True)

    fig.canvas.mpl_connect("button_press_event", on_click)

    with TeleopMain.from_config_file(args.config) as teleop:

        def update(_frame_num: int) -> None:
            nonlocal frames, last_print_s, latest_sample, visual_frame_state
            frames += 1
            latest_sample = teleop.step()
            if visual_frame_state is None:
                visual_frame_state = visual_frame_state_from_sample(latest_sample)
            ax.clear()
            origin = np.zeros(3, dtype=np.float64)
            all_points: list[np.ndarray] = [origin] if args.include_origin else []

            draw_world_axes(
                ax,
                display_frame=display_frame,
                length=float(args.world_axis_length),
                label="head-hand origin",
            )
            all_points.append(draw_fixed_head_pose(ax, display_frame=display_frame))

            if visual_frame_state is None:
                set_equal_axes(ax, all_points, float(args.axis_limit))
                ax.set_xlabel("+X forward")
                ax.set_ylabel("+Y left")
                ax.set_zlabel("+Z up")
                apply_view()
                ax.legend(loc="upper left", fontsize=8)
                ax.set_title(
                    "AVP/MANUS Teleop Visualizer | waiting for head + both wrist poses"
                )
                return

            for side, color in SIDE_COLORS.items():
                pose = latest_sample["ee_poses"][side]
                local_pose_mat = (
                    pose_to_visual_frame_matrix(pose, visual_frame_state)
                    if pose is not None
                    else None
                )
                pose_mat = (
                    transform_pose_matrix(local_pose_mat, display_frame)
                    if local_pose_mat is not None
                    else None
                )
                skeleton = skeleton_to_visual_frame(
                    latest_sample["hand_skeletons"][side],
                    visual_frame_state,
                )

                if skeleton is not None:
                    points = draw_openxr_skeleton(
                        ax,
                        skeleton,
                        display_frame=display_frame,
                        color=color,
                        alpha=0.8,
                    )
                    all_points.extend(points)

                if pose_mat is not None:
                    pos = pose_mat[:3, 3]
                    all_points.append(pos)
                    if args.trail > 0:
                        trails[side].append(pos.copy())
                    ax.scatter(
                        pos[0],
                        pos[1],
                        pos[2],
                        color=color,
                        edgecolors="black",
                        linewidths=0.8,
                        s=190,
                        label=f"{side} EE",
                        zorder=10,
                    )
                    arrow_rot = (
                        geometric_hand_frame(skeleton, side=side)
                        if args.ee_arrow_mode == "hand"
                        else None
                    )
                    if arrow_rot is None:
                        arrow_rot = local_pose_mat[:3, :3]
                    arrow_rot = transform_rotation(arrow_rot, display_frame)
                    draw_pose_axes(
                        ax,
                        pos,
                        arrow_rot,
                        length=float(args.arrow_length),
                    )

                    if skeleton is None or skeleton_points(skeleton).size == 0:
                        fallback_points = draw_fallback_hand(
                            ax,
                            pose_mat=local_pose_mat,
                            joint_names=latest_sample["hand_joint_names"][side],
                            joint_positions=latest_sample["hand_joint_positions"][side],
                            side=side,
                            color=color,
                            display_frame=display_frame,
                            scale=float(args.fallback_hand_scale),
                        )
                        all_points.extend(fallback_points)

                trail = np.asarray(trails[side], dtype=np.float64)
                if trail.shape[0] > 1:
                    ax.plot(
                        trail[:, 0],
                        trail[:, 1],
                        trail[:, 2],
                        color=color,
                        linestyle="--",
                        linewidth=1.0,
                        alpha=0.25,
                    )
                    all_points.extend(list(trail))

            set_equal_axes(ax, all_points, float(args.axis_limit))
            ax.set_xlabel("+X forward")
            ax.set_ylabel("+Y left")
            ax.set_zlabel("+Z up")
            apply_view()
            ax.legend(loc="upper left", fontsize=8)
            elapsed_s = max(time.monotonic() - start_s, 1e-6)
            ax.set_title(
                "AVP/MANUS Teleop Visualizer | "
                f"frame={latest_sample['frame_count']} "
                f"fps={frames / elapsed_s:.1f} "
                f"view={VIEW_PRESETS[view_index][0]} "
                "click=flip view"
            )

            now_s = time.monotonic()
            if now_s - last_print_s >= 2.0:
                last_print_s = now_s
                chunks = []
                for side in SIDE_COLORS:
                    pose = latest_sample["ee_poses"][side]
                    if pose is None:
                        chunks.append(f"{side}=missing")
                    else:
                        pos = pose_to_visual_frame_matrix(
                            pose,
                            visual_frame_state,
                        )[:3, 3]
                        chunks.append(f"{side}={np.round(pos, 3)}")
                print(
                    f"frame={latest_sample['frame_count']} " + " ".join(chunks),
                    flush=True,
                )

        interval_ms = max(int(1000.0 / max(float(args.fps), 1e-3)), 16)
        _animation = FuncAnimation(
            fig,
            update,
            interval=interval_ms,
            cache_frame_data=False,
        )
        try:
            plt.show()
        except KeyboardInterrupt:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
