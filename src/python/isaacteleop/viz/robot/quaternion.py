# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Quaternion algebra, in numpy, ``wxyz`` throughout.

``wxyz`` because that is the scene's order and the order these compose in; a controller's
``GRIP_ORIENTATION`` is ``xyzw`` and must be reordered at the boundary, field by field,
never sliced. :func:`~isaacteleop.viz.robot.is_unit` is the guard for anything read off a
device -- every function here assumes a unit quaternion and none checks.
"""

from __future__ import annotations

import math

import numpy as np

#: Below this a quaternion carries no usable orientation. Matches the SO-101 clutch's
#: own degenerate-quaternion threshold (``clutch_retargeter.py``).
MIN_QUAT_NORM = 1e-6


def multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """``a * b``: the rotation that applies ``b`` first, then ``a``."""
    aw, ax, ay, az = np.asarray(a, dtype=float)
    bw, bx, by, bz = np.asarray(b, dtype=float)
    return np.array(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ]
    )


def conjugate(q: np.ndarray) -> np.ndarray:
    """The inverse rotation, for a unit quaternion."""
    w, x, y, z = np.asarray(q, dtype=float)
    return np.array([w, -x, -y, -z])


def rotate(v: np.ndarray, q: np.ndarray) -> np.ndarray:
    """``v`` turned by a UNIT quaternion.

    For a non-unit one this LERPS toward ``v`` by ``|q|^2`` rather than scaling the
    result, so a short quaternion silently shrinks the rotation while keeping it in
    plane: norm 0.9 turns a 30 deg yaw into 24.4 deg with nothing to notice it by.
    """
    q = np.asarray(q, dtype=float)
    v = np.asarray(v, dtype=float)
    t = 2.0 * np.cross(q[1:4], v)
    return v + q[0] * t + np.cross(q[1:4], t)


def from_axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    """A rotation of ``angle`` radians about a UNIT ``axis``."""
    half = 0.5 * float(angle)
    return np.concatenate(
        ([math.cos(half)], math.sin(half) * np.asarray(axis, dtype=float))
    )


def to_matrix(q: np.ndarray) -> np.ndarray:
    """A UNIT quaternion as a 3x3 rotation matrix."""
    w, x, y, z = np.asarray(q, dtype=float)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def from_matrix(m: np.ndarray) -> np.ndarray:
    """A 3x3 rotation matrix as a quaternion, sign-normalised to ``w >= 0``.

    Shepperd's method: the branch with the largest divisor is taken, because the naive
    ``w``-first formula loses all precision as the trace approaches -1 -- exactly the
    half-turns a robot's wrist reaches.
    """
    m = np.asarray(m, dtype=float).reshape(3, 3)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        q = np.array(
            [
                0.25 * s,
                (m[2, 1] - m[1, 2]) / s,
                (m[0, 2] - m[2, 0]) / s,
                (m[1, 0] - m[0, 1]) / s,
            ]
        )
    else:
        i = int(np.argmax(np.diag(m)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(1.0 + m[i, i] - m[j, j] - m[k, k]) * 2.0
        q = np.empty(4)
        q[0] = (m[k, j] - m[j, k]) / s
        q[1 + i] = 0.25 * s
        q[1 + j] = (m[j, i] + m[i, j]) / s
        q[1 + k] = (m[k, i] + m[i, k]) / s
    # The two signs are the same rotation; pinning one keeps a measured constant
    # comparable with the next measurement of it.
    return -q if q[0] < 0.0 else q
