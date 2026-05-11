# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""World / head / lazy locked placements, ported from
``examples/camera_streamer/operators/xr_plane_renderer/camera_plane.cpp``.

Parameter names, defaults, and state-machine semantics are identical to
the original ``CameraPlaneConfig`` so existing tuning carries over.
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple

from ._math import (
    Quat,
    Vec3,
    angle_between_xz_deg,
    normalize_angle,
    project_forward_xz,
    quat_mul,
    rotate_vec,
    smoothstep,
    yaw_quat,
)


@dataclass(frozen=True)
class PlacementConfig:
    """Mirrors ``CameraPlaneConfig`` (camera_plane.hpp:29).

    ``size_meters`` is plane width/height in world units. The lazy-mode
    fields are no-ops for World / Head locks.
    """

    size_meters: Tuple[float, float] = (1.0, 0.5625)
    distance: float = 1.5
    offset_x: float = 0.0
    offset_y: float = 0.0
    look_away_angle_deg: float = 45.0
    reposition_distance: float = 0.5
    reposition_delay_s: float = 0.5
    transition_duration_s: float = 0.3


@dataclass
class Placement:
    """Output of a strategy: feeds straight into ``viz.QuadLayerPlacement``."""

    position: Vec3
    orientation: Quat  # (w, x, y, z)
    size_meters: Tuple[float, float]


class PlacementStrategy(ABC):
    """Per-layer placement policy. ``update`` is called from the render
    thread each frame; implementations must be cheap and pure-CPU."""

    @abstractmethod
    def update(self, head_pos: Vec3, head_orientation: Quat) -> Placement: ...


def _target_position(head_pos: Vec3, forward_xz: Vec3, cfg: PlacementConfig) -> Vec3:
    """Place the quad ``distance`` ahead, with right-vector / up-vector offsets.
    Mirrors ``CameraPlane::compute_target_position``."""
    right_x = -forward_xz[2]
    right_z = forward_xz[0]
    return (
        head_pos[0] + forward_xz[0] * cfg.distance + right_x * cfg.offset_x,
        head_pos[1] + cfg.offset_y,
        head_pos[2] + forward_xz[2] * cfg.distance + right_z * cfg.offset_x,
    )


def _yaw_to_face(target: Vec3, plane_pos: Vec3) -> float:
    """Yaw rotation that aims the plane's front at ``target``.
    Mirrors ``CameraPlane::compute_yaw_to_face``."""
    return math.atan2(target[0] - plane_pos[0], target[2] - plane_pos[2])


class WorldLocked(PlacementStrategy):
    """Place once in front of the user; never move thereafter.
    Mirrors ``CameraPlane::update_world``."""

    def __init__(self, config: PlacementConfig) -> None:
        self._config = config
        self._cached: Optional[Placement] = None

    def update(self, head_pos: Vec3, head_orientation: Quat) -> Placement:
        if self._cached is None:
            forward_xz = project_forward_xz(head_orientation)
            position = _target_position(head_pos, forward_xz, self._config)
            yaw = _yaw_to_face(head_pos, position)
            self._cached = Placement(position, yaw_quat(yaw), self._config.size_meters)
        return self._cached


# 180° about +Y: rotates the quad to face back at the user.
_ROT_Y_180: Quat = (0.0, 0.0, 1.0, 0.0)


class HeadLocked(PlacementStrategy):
    """Follow the head every frame, full 6-DoF.
    Mirrors ``CameraPlane::update_head`` + the ``head_rotation * rotY(π)``
    in ``CameraPlane::rotation``."""

    def __init__(self, config: PlacementConfig) -> None:
        self._config = config

    def update(self, head_pos: Vec3, head_orientation: Quat) -> Placement:
        forward = rotate_vec(head_orientation, (0.0, 0.0, -1.0))
        right = rotate_vec(head_orientation, (1.0, 0.0, 0.0))
        up = rotate_vec(head_orientation, (0.0, 1.0, 0.0))
        d, ox, oy = self._config.distance, self._config.offset_x, self._config.offset_y
        position = (
            head_pos[0] + forward[0] * d + right[0] * ox + up[0] * oy,
            head_pos[1] + forward[1] * d + right[1] * ox + up[1] * oy,
            head_pos[2] + forward[2] * d + right[2] * ox + up[2] * oy,
        )
        orientation = quat_mul(head_orientation, _ROT_Y_180)
        return Placement(position, orientation, self._config.size_meters)


class LazyLocked(PlacementStrategy):
    """World-locked, but smoothly re-snaps in front of the user when they
    look away (or drift) past a threshold for ``reposition_delay_s``.

    Mirrors ``CameraPlane::update_lazy`` + ``::update_transition``.
    """

    def __init__(self, config: PlacementConfig) -> None:
        self._config = config
        self._initialized = False
        self._position: Vec3 = (0.0, 0.0, 0.0)
        self._yaw: float = 0.0
        self._is_looking_away = False
        self._look_away_start_t = 0.0
        self._is_transitioning = False
        self._transition_start_t = 0.0
        self._transition_start_position: Vec3 = (0.0, 0.0, 0.0)
        self._transition_start_yaw = 0.0
        self._target_position: Vec3 = (0.0, 0.0, 0.0)
        self._target_yaw = 0.0

    def update(self, head_pos: Vec3, head_orientation: Quat) -> Placement:
        now = time.monotonic()
        forward_xz = project_forward_xz(head_orientation)

        if not self._initialized:
            self._position = _target_position(head_pos, forward_xz, self._config)
            self._target_position = self._position
            self._yaw = _yaw_to_face(head_pos, self._position)
            self._target_yaw = self._yaw
            self._initialized = True
            return Placement(
                self._position, yaw_quat(self._yaw), self._config.size_meters
            )

        # Look-away check: angle between head forward and head→plane vector.
        head_to_plane = (
            self._position[0] - head_pos[0],
            0.0,
            self._position[2] - head_pos[2],
        )
        angle = angle_between_xz_deg(forward_xz, head_to_plane)
        angle_triggered = angle > self._config.look_away_angle_deg

        # Position drift check: user has moved far from the ideal placement.
        ideal = _target_position(head_pos, forward_xz, self._config)
        drift = math.sqrt(sum((self._position[i] - ideal[i]) ** 2 for i in range(3)))
        position_triggered = (
            self._config.reposition_distance > 0.0
            and drift > self._config.reposition_distance
        )

        if angle_triggered or position_triggered:
            if not self._is_looking_away:
                self._is_looking_away = True
                self._look_away_start_t = now
            elif not self._is_transitioning:
                if (now - self._look_away_start_t) >= self._config.reposition_delay_s:
                    self._target_position = ideal
                    self._target_yaw = _yaw_to_face(head_pos, self._target_position)
                    self._transition_start_position = self._position
                    self._transition_start_yaw = self._yaw
                    self._transition_start_t = now
                    self._is_transitioning = True
        else:
            self._is_looking_away = False

        if self._is_transitioning:
            dur = self._config.transition_duration_s
            t = min((now - self._transition_start_t) / dur, 1.0) if dur > 0.0 else 1.0
            s = smoothstep(t)
            self._position = tuple(
                self._transition_start_position[i]
                + (self._target_position[i] - self._transition_start_position[i]) * s
                for i in range(3)
            )  # type: ignore[assignment]
            yaw_diff = normalize_angle(self._target_yaw - self._transition_start_yaw)
            self._yaw = self._transition_start_yaw + yaw_diff * s
            if t >= 1.0:
                self._is_transitioning = False
                self._is_looking_away = False

        return Placement(self._position, yaw_quat(self._yaw), self._config.size_meters)


def build(lock_mode: str, config: PlacementConfig) -> PlacementStrategy:
    """Factory used by the YAML loader.

    Mode strings match camera_streamer's ``parse_lock_mode``:
    ``"world"`` → WorldLocked, ``"head"`` → HeadLocked, anything else
    (including ``"lazy"``) → LazyLocked.
    """
    if lock_mode == "world":
        return WorldLocked(config)
    if lock_mode == "head":
        return HeadLocked(config)
    return LazyLocked(config)
