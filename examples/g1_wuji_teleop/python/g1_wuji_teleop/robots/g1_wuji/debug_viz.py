# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Optional point/axis debug visualization helpers for the G1-Wuji teleop.

Keep marker creation, head-prim lookup, and per-frame debug updates here so the
teleop control path stays independent of debug-only scene edits.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np


MarkerPoseResolver = Callable[
    [str, Mapping[str, Any]], tuple[np.ndarray, np.ndarray] | None
]
FramePose = tuple[np.ndarray, np.ndarray]


@dataclass(frozen=True)
class DebugVizRuntimeConfig:
    enabled: bool = True


@dataclass(frozen=True)
class DebugVizSceneConfig:
    wrist_marker_radius: float
    wrist_axis_length: float
    wrist_axis_radius: float
    robot_z: float


@dataclass
class DebugVizHandles:
    wrist_markers: Any | None = None
    wrist_frames: Any | None = None
    robot_ee_frames: Any | None = None
    head_link_point: Any | None = None
    head_link_frame: Any | None = None


def walk_child_prims(root_prim: Any):
    if not root_prim or not root_prim.IsValid():
        return
    yield root_prim
    for child in root_prim.GetChildren():
        yield from walk_child_prims(child)


def find_child_prim_by_name(root_prim: Any, target_name: str) -> Any | None:
    for prim in walk_child_prims(root_prim):
        if prim.GetName() == target_name:
            return prim
    return None


def head_like_relative_paths() -> tuple[str, ...]:
    return (
        "torso_link/head_link",
        "g1/torso_link/head_link",
        "torso_link/visuals/head_link",
        "g1/torso_link/visuals/head_link",
        "head_link",
        "g1/head_link",
        "head",
        "g1/head",
    )


def find_head_like_prim(stage: Any, root_prim: Any, root_path: str) -> Any | None:
    if stage is not None:
        for relative_path in head_like_relative_paths():
            prim = stage.GetPrimAtPath(f"{root_path}/{relative_path}")
            if prim is not None and prim.IsValid():
                return prim
        for prim in stage.Traverse():
            prim_path = str(prim.GetPath())
            if any(
                prim_path.endswith(f"/{suffix}")
                for suffix in head_like_relative_paths()
            ):
                return prim

    for name in ("head_link", "head"):
        match = find_child_prim_by_name(root_prim, name)
        if match is not None and "/visuals/" not in str(match.GetPath()):
            return match
    for prim in walk_child_prims(root_prim):
        prim_path = str(prim.GetPath())
        if "/visuals/" in prim_path:
            continue
        if "head" in prim.GetName().lower():
            return prim
    return None


def debug_viz_runtime_config(config: Mapping[str, Any]) -> DebugVizRuntimeConfig:
    robot_config = config.get("robot", {})
    if robot_config is None:
        robot_config = {}
    if not isinstance(robot_config, Mapping):
        raise ValueError("Config field 'robot' must be a mapping")

    # Keep debug visualization as a single on/off switch for this teleop path.
    debug_viz_config = robot_config.get("debug_visualization", True)
    if debug_viz_config is None:
        debug_viz_config = True
    if not isinstance(debug_viz_config, bool):
        raise ValueError("Config field 'robot.debug_visualization' must be a boolean")

    return DebugVizRuntimeConfig(enabled=debug_viz_config)


def _make_axis_marker_set(
    sim_utils: Any,
    VisualizationMarkers: Any,
    VisualizationMarkersCfg: Any,
    *,
    prim_path: str,
    axis_length: float,
    axis_radius: float,
    anchor_x: float,
    robot_z: float,
    colors: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
) -> Any:
    axis_cfg = VisualizationMarkersCfg(
        prim_path=prim_path,
        markers={
            "x": sim_utils.CylinderCfg(
                radius=axis_radius,
                height=axis_length,
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=colors[0]),
            ),
            "y": sim_utils.CylinderCfg(
                radius=axis_radius,
                height=axis_length,
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=colors[1]),
            ),
            "z": sim_utils.CylinderCfg(
                radius=axis_radius,
                height=axis_length,
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=colors[2]),
            ),
        },
    )
    axis_markers = VisualizationMarkers(axis_cfg)
    axis_markers.visualize(
        translations=np.array(
            [
                [anchor_x + axis_length * 0.5, 0.25, robot_z + 0.85],
                [anchor_x, 0.25 + axis_length * 0.5, robot_z + 0.85],
                [anchor_x, 0.25, robot_z + 0.85 + axis_length * 0.5],
                [anchor_x + axis_length * 0.5, -0.25, robot_z + 0.85],
                [anchor_x, -0.25 + axis_length * 0.5, robot_z + 0.85],
                [anchor_x, -0.25, robot_z + 0.85 + axis_length * 0.5],
            ],
            dtype=np.float32,
        ),
        orientations=np.array(
            [
                _axis_to_cylinder_orientation(np.array([1.0, 0.0, 0.0])),
                _axis_to_cylinder_orientation(np.array([0.0, 1.0, 0.0])),
                _axis_to_cylinder_orientation(np.array([0.0, 0.0, 1.0])),
                _axis_to_cylinder_orientation(np.array([1.0, 0.0, 0.0])),
                _axis_to_cylinder_orientation(np.array([0.0, 1.0, 0.0])),
                _axis_to_cylinder_orientation(np.array([0.0, 0.0, 1.0])),
            ],
            dtype=np.float32,
        ),
        marker_indices=np.array([0, 1, 2, 0, 1, 2], dtype=np.int32),
    )
    return axis_markers


def _make_point_marker_set(
    sim_utils: Any,
    VisualizationMarkers: Any,
    VisualizationMarkersCfg: Any,
    *,
    prim_path: str,
    radius: float,
    anchor_x: float,
    anchor_y: float,
    robot_z: float,
    color: tuple[float, float, float],
) -> Any:
    marker_cfg = VisualizationMarkersCfg(
        prim_path=prim_path,
        markers={
            "point": sim_utils.SphereCfg(
                radius=radius,
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=color),
            ),
        },
    )
    point_markers = VisualizationMarkers(marker_cfg)
    point_markers.visualize(
        translations=np.array(
            [[anchor_x, anchor_y, robot_z + 0.85]],
            dtype=np.float32,
        ),
        marker_indices=np.array([0], dtype=np.int32),
    )
    return point_markers


def create_debug_viz(
    *,
    sim_utils: Any,
    VisualizationMarkers: Any,
    VisualizationMarkersCfg: Any,
    scene_config: DebugVizSceneConfig,
    runtime_config: DebugVizRuntimeConfig,
) -> DebugVizHandles:
    handles = DebugVizHandles()
    if not runtime_config.enabled:
        return handles

    marker_cfg = VisualizationMarkersCfg(
        prim_path="/World/TeleopTargets/WristMarkers",
        markers={
            "left": sim_utils.SphereCfg(
                radius=scene_config.wrist_marker_radius,
                visual_material=sim_utils.PreviewSurfaceCfg(
                    diffuse_color=(0.1, 0.35, 1.0)
                ),
            ),
            "right": sim_utils.SphereCfg(
                radius=scene_config.wrist_marker_radius,
                visual_material=sim_utils.PreviewSurfaceCfg(
                    diffuse_color=(1.0, 0.35, 0.1)
                ),
            ),
        },
    )
    handles.wrist_markers = VisualizationMarkers(marker_cfg)
    handles.wrist_markers.visualize(
        translations=np.array(
            [
                [0.35, 0.25, scene_config.robot_z + 0.85],
                [0.35, -0.25, scene_config.robot_z + 0.85],
            ],
            dtype=np.float32,
        ),
        marker_indices=np.array([0, 1], dtype=np.int32),
    )

    handles.wrist_frames = _make_axis_marker_set(
        sim_utils,
        VisualizationMarkers,
        VisualizationMarkersCfg,
        prim_path="/World/TeleopTargets/WristAxes",
        axis_length=scene_config.wrist_axis_length,
        axis_radius=scene_config.wrist_axis_radius,
        anchor_x=0.35,
        robot_z=scene_config.robot_z,
        colors=((1.0, 0.1, 0.1), (0.1, 0.9, 0.1), (0.1, 0.3, 1.0)),
    )

    handles.robot_ee_frames = _make_axis_marker_set(
        sim_utils,
        VisualizationMarkers,
        VisualizationMarkersCfg,
        prim_path="/World/TeleopTargets/RobotEeAxes",
        axis_length=scene_config.wrist_axis_length,
        axis_radius=scene_config.wrist_axis_radius,
        anchor_x=0.2,
        robot_z=scene_config.robot_z,
        colors=((1.0, 0.1, 0.1), (0.1, 0.9, 0.1), (0.1, 0.3, 1.0)),
    )

    handles.head_link_point = _make_point_marker_set(
        sim_utils,
        VisualizationMarkers,
        VisualizationMarkersCfg,
        prim_path="/World/TeleopTargets/RobotHeadLinkPoint",
        radius=scene_config.wrist_marker_radius * 1.15,
        anchor_x=-0.2,
        anchor_y=0.0,
        robot_z=scene_config.robot_z,
        color=(0.1, 0.95, 0.95),
    )
    handles.head_link_frame = _make_axis_marker_set(
        sim_utils,
        VisualizationMarkers,
        VisualizationMarkersCfg,
        prim_path="/World/TeleopTargets/RobotHeadLinkAxes",
        axis_length=scene_config.wrist_axis_length,
        axis_radius=scene_config.wrist_axis_radius,
        anchor_x=-0.2,
        robot_z=scene_config.robot_z,
        colors=((1.0, 0.1, 0.1), (0.1, 0.9, 0.1), (0.1, 0.3, 1.0)),
    )

    return handles


def update_wrist_markers(
    point_markers: Any | None,
    frame_markers: Any | None,
    target_poses: Mapping[str, FramePose],
    axis_length: float,
) -> None:
    if point_markers is None and frame_markers is None:
        return

    translations: list[np.ndarray] = []
    marker_indices: list[int] = []
    axis_translations: list[np.ndarray] = []
    axis_orientations: list[np.ndarray] = []
    axis_indices: list[int] = []
    for marker_index, side in enumerate(("left", "right")):
        target = target_poses.get(side)
        if target is None:
            continue
        position, rotation = target
        if point_markers is not None:
            translations.append(position)
            marker_indices.append(marker_index)
        if frame_markers is not None:
            for axis_index in range(3):
                axis = rotation[:, axis_index]
                axis_translations.append(
                    position + axis.astype(np.float32) * 0.5 * axis_length
                )
                axis_orientations.append(_axis_to_cylinder_orientation(axis))
                axis_indices.append(axis_index)
    if point_markers is not None and translations:
        point_markers.visualize(
            translations=np.stack(translations),
            marker_indices=np.asarray(marker_indices, dtype=np.int32),
        )
    if frame_markers is not None and axis_translations:
        frame_markers.visualize(
            translations=np.stack(axis_translations),
            orientations=np.stack(axis_orientations),
            marker_indices=np.asarray(axis_indices, dtype=np.int32),
        )


def update_frame_axis_markers(
    frame_markers: Any | None,
    frame_poses: Mapping[str, FramePose],
    axis_length: float,
) -> None:
    if frame_markers is None:
        return
    axis_translations: list[np.ndarray] = []
    axis_orientations: list[np.ndarray] = []
    axis_indices: list[int] = []
    for side in ("left", "right"):
        frame_pose = frame_poses.get(side)
        if frame_pose is None:
            continue

        position, rotation = frame_pose
        for axis_index in range(3):
            axis = rotation[:, axis_index]
            axis_translations.append(
                position + axis.astype(np.float32) * 0.5 * axis_length
            )
            axis_orientations.append(_axis_to_cylinder_orientation(axis))
            axis_indices.append(axis_index)
    if axis_translations:
        frame_markers.visualize(
            translations=np.stack(axis_translations),
            orientations=np.stack(axis_orientations),
            marker_indices=np.asarray(axis_indices, dtype=np.int32),
        )


def update_point_marker(
    point_markers: Any | None,
    frame_pose: FramePose | None,
) -> None:
    if point_markers is None or frame_pose is None:
        return
    position, _rotation = frame_pose
    point_markers.visualize(
        translations=np.asarray([position], dtype=np.float32),
        marker_indices=np.array([0], dtype=np.int32),
    )


def update_head_marker(
    handles: DebugVizHandles,
    *,
    head_link_prim: Any | None,
    xform_cache: Any | None,
) -> None:
    if head_link_prim is None or xform_cache is None:
        return

    xform_cache.Clear()
    head_world = xform_cache.GetLocalToWorldTransform(head_link_prim)
    head_translation = np.asarray(head_world.ExtractTranslation(), dtype=np.float32)
    head_rotation = np.asarray(head_world.ExtractRotationMatrix(), dtype=np.float32)
    head_pose = (head_translation, head_rotation)
    update_point_marker(handles.head_link_point, head_pose)
    update_frame_axis_markers(
        handles.head_link_frame,
        {"head": head_pose},
        axis_length=0.18,
    )


def sample_target_poses(
    sample: Mapping[str, Any],
    *,
    resolve_marker_pose: MarkerPoseResolver,
) -> dict[str, FramePose]:
    target_poses: dict[str, FramePose] = {}
    for side in ("left", "right"):
        ee_poses = sample.get("ee_poses", {})
        pose = ee_poses.get(side) if isinstance(ee_poses, Mapping) else None
        if pose is None:
            continue
        target = resolve_marker_pose(side, pose)
        if target is None:
            continue
        target_poses[side] = target
    return target_poses


def _axis_to_cylinder_orientation(axis: np.ndarray) -> np.ndarray:
    axis = np.asarray(axis, dtype=np.float64)
    axis_norm = np.linalg.norm(axis)
    if axis_norm < 1.0e-8:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    z_axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    target = axis / axis_norm
    dot = float(np.clip(np.dot(z_axis, target), -1.0, 1.0))
    if dot > 1.0 - 1.0e-8:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    if dot < -1.0 + 1.0e-8:
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    rot_axis = np.cross(z_axis, target)
    rot_axis /= np.linalg.norm(rot_axis)
    angle = np.arccos(dot)
    half = angle * 0.5
    quat = np.concatenate((rot_axis * np.sin(half), [np.cos(half)])).astype(np.float32)
    quat /= np.linalg.norm(quat)
    return quat
