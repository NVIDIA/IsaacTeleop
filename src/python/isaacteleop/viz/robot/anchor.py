# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Horizontal bearing, and where operator-anchored content goes.

Every pose here is in a gravity-aligned Y-up XR reference space -- ``LOCAL``,
``LOCAL_FLOOR``, ``STAGE`` or ``UNBOUNDED`` -- where +Y is world up. A ``VIEW``-space pose
yields a silently wrong bearing rather than an error. Poses stay correct across a runtime
recentre; a yaw LATCHED across one does not, so re-anchor on
``XrEventDataReferenceSpaceChangePending``.
"""

from __future__ import annotations

import math

import numpy as np

from .quaternion import rotate


#: How far a quaternion's norm may sit from 1 and still carry a usable rotation: wide
#: enough for a float32 round-trip, far tighter than the shrinkage
#: :func:`~isaacteleop.viz.robot.quaternion.rotate` would otherwise apply in silence.
UNIT_QUAT_TOL = 1e-3


def is_unit(q: np.ndarray) -> bool:
    """Whether ``q`` is finite and unit to :data:`UNIT_QUAT_TOL`.

    Layout-agnostic, and exactly what every turning function here rejects, so a caller
    reading a quaternion off a device has one predicate to gate on.
    """
    q = np.asarray(q, dtype=float)
    if not np.all(np.isfinite(q)):
        return False
    return abs(float(np.linalg.norm(q)) - 1.0) <= UNIT_QUAT_TOL


def yaw_of_direction(forward_xr: np.ndarray, fallback_xr: np.ndarray) -> np.ndarray:
    """The horizontal bearing of an XR direction, as a wxyz quaternion about +Y.

    ``forward_xr`` must be unit length: the near-vertical test is an absolute 1e-6, so a
    magnified direction a hair off vertical returns a garbage bearing. ``fallback_xr``
    covers a direction within a hair of vertical; callers pass the pose's own up-vector,
    which holds heading up to and at vertical (past it, the bearing reverses).
    """
    forward = np.asarray(forward_xr, dtype=float)
    if abs(forward[0]) < 1e-6 and abs(forward[2]) < 1e-6:
        # Straight up or down. The fallback then points along the horizon: forwards when
        # the direction points down, backwards when up.
        forward = -math.copysign(1.0, forward[1]) * np.asarray(fallback_xr, dtype=float)

    half = 0.5 * math.atan2(-forward[0], -forward[2])
    return np.array([math.cos(half), 0.0, math.sin(half), 0.0])


def yaw_of_axis(q_xyzw: np.ndarray, forward_local: np.ndarray) -> np.ndarray:
    """The horizontal facing of an XR orientation, as a wxyz quaternion about +Y.

    ``forward_local`` names which axis of the pose is its facing, in the pose's own
    frame. No default: each axis is blind to rotation about itself and sensitive to the
    rest, so it must be chosen against the motions the reading has to ignore.
    """
    q_wxyz = np.asarray(q_xyzw, dtype=float)[[3, 0, 1, 2]]
    # Raise on genuinely broken input, absorb float drift; see `rotate` on what a short
    # quaternion does if let through. Callers gate on `is_unit` rather than catch this.
    if not is_unit(q_wxyz):
        raise ValueError(
            f"q_xyzw must be a unit quaternion; norm is {float(np.linalg.norm(q_wxyz))}"
        )
    q_wxyz = q_wxyz / float(np.linalg.norm(q_wxyz))
    forward = rotate(np.asarray(forward_local, dtype=float), q_wxyz)
    up = rotate(np.array([0.0, 1.0, 0.0]), q_wxyz)
    return yaw_of_direction(forward, up)


def yaw_of(q_xyzw: np.ndarray) -> np.ndarray:
    """The horizontal facing of a HEAD pose, reading its -Z as the view direction."""
    return yaw_of_axis(q_xyzw, np.array([0.0, 0.0, -1.0]))


def anchor_from_head(
    head_pose_xr: np.ndarray, offset_xr: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Where content anchored to the operator goes, from a 7-D head pose.

    Takes ``(position, xyzw)`` in XR and an offset in the head's yaw frame; returns the XR
    position and the head's yaw as a wxyz quaternion, which both carries ``offset_xr`` onto
    the head's facing and turns the caller's content. Gravity-aligned, so content whose
    correct pose is not level cannot be placed by this.
    """
    pose = np.asarray(head_pose_xr, dtype=float)
    q_yaw = yaw_of(pose[3:7])
    offset = rotate(np.asarray(offset_xr, dtype=float), q_yaw)
    return pose[:3] + offset, q_yaw
