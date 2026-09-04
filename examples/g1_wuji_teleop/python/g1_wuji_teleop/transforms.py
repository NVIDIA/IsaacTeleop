# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small transform helpers used by the G1-Wuji teleop example."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def normalize_quat_xyzw(quat: Sequence[float]) -> np.ndarray:
    quat_array = np.asarray(quat, dtype=np.float64).reshape(4)
    norm = float(np.linalg.norm(quat_array))
    if norm < 1.0e-12:
        raise ValueError("Quaternion must be non-zero.")
    return quat_array / norm


def quat_xyzw_to_matrix(quat: Sequence[float]) -> np.ndarray:
    x, y, z, w = normalize_quat_xyzw(quat)
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return np.array(
        [
            [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
            [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
            [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
        ],
        dtype=np.float64,
    )


def quat_xyzw_multiply(
    lhs: Sequence[float],
    rhs: Sequence[float],
) -> np.ndarray:
    lx, ly, lz, lw = normalize_quat_xyzw(lhs)
    rx, ry, rz, rw = normalize_quat_xyzw(rhs)
    return normalize_quat_xyzw(
        [
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        ]
    )


def transform_controller_pose_to_palm(
    *,
    controller_pos: Sequence[float],
    controller_quat_xyzw: Sequence[float],
    offset_pos: Sequence[float],
    offset_quat_xyzw: Sequence[float],
) -> tuple[np.ndarray, np.ndarray]:
    controller_pos_array = np.asarray(controller_pos, dtype=np.float64).reshape(3)
    offset_pos_array = np.asarray(offset_pos, dtype=np.float64).reshape(3)
    controller_rot = quat_xyzw_to_matrix(controller_quat_xyzw)
    palm_pos = controller_pos_array + controller_rot @ offset_pos_array
    palm_quat = quat_xyzw_multiply(controller_quat_xyzw, offset_quat_xyzw)
    return palm_pos, palm_quat
