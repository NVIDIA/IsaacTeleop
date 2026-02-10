# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Transform Utilities - Shared math for applying 4x4 transforms to poses.

Provides functions to apply a 4x4 homogeneous transformation matrix to
position vectors and orientation quaternions. Uses only numpy (no scipy).

Quaternion Convention:
    Throughout this module, quaternions are stored as [x, y, z, w] arrays,
    matching the order written by the DeviceIO source nodes (head_source.py,
    hands_source.py, controllers_source.py).
"""

import numpy as np
from typing import Tuple


def validate_transform_matrix(matrix: np.ndarray) -> np.ndarray:
    """
    Validate and normalize a 4x4 homogeneous transformation matrix.

    Args:
        matrix: A (4, 4) numpy array representing the transform.

    Returns:
        The validated matrix as float64.

    Raises:
        ValueError: If matrix shape is not (4, 4) or bottom row is invalid.
    """
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (4, 4):
        raise ValueError(f"Transform matrix must be (4, 4), got {matrix.shape}")

    # Validate bottom row is [0, 0, 0, 1]
    expected_bottom = np.array([0.0, 0.0, 0.0, 1.0])
    if not np.allclose(matrix[3, :], expected_bottom, atol=1e-6):
        raise ValueError(
            f"Bottom row of transform matrix must be [0, 0, 0, 1], "
            f"got {matrix[3, :]}"
        )

    return matrix


def decompose_transform(matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Decompose a 4x4 homogeneous transform into rotation and translation.

    Args:
        matrix: A (4, 4) homogeneous transformation matrix.

    Returns:
        Tuple of:
            - rotation: (3, 3) rotation matrix
            - translation: (3,) translation vector
    """
    rotation = matrix[:3, :3]
    translation = matrix[:3, 3]
    return rotation, translation


def transform_position(
    position: np.ndarray,
    rotation_3x3: np.ndarray,
    translation: np.ndarray
) -> np.ndarray:
    """
    Apply a rigid transform to a position vector: p' = R @ p + t.

    Args:
        position: (3,) position vector.
        rotation_3x3: (3, 3) rotation matrix.
        translation: (3,) translation vector.

    Returns:
        (3,) transformed position as float32.
    """
    result: np.ndarray = (rotation_3x3 @ position + translation).astype(np.float32)
    return result


def transform_positions_batch(
    positions: np.ndarray,
    rotation_3x3: np.ndarray,
    translation: np.ndarray
) -> np.ndarray:
    """
    Apply a rigid transform to a batch of position vectors: p' = R @ p + t.

    Args:
        positions: (N, 3) position vectors.
        rotation_3x3: (3, 3) rotation matrix.
        translation: (3,) translation vector.

    Returns:
        (N, 3) transformed positions as float32.
    """
    # (N, 3) @ (3, 3)^T + (3,) = (N, 3)
    result: np.ndarray = (positions @ rotation_3x3.T + translation).astype(np.float32)
    return result


# ============================================================================
# Quaternion helpers (pure numpy, no scipy)
# ============================================================================

def _rotation_matrix_to_quat_xyzw(R: np.ndarray) -> np.ndarray:
    """
    Convert a 3x3 rotation matrix to a quaternion in [x, y, z, w] format.

    Uses Shepperd's method for numerical stability.

    Args:
        R: (3, 3) rotation matrix.

    Returns:
        (4,) quaternion [x, y, z, w].
    """
    trace = R[0, 0] + R[1, 1] + R[2, 2]

    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s

    return np.array([x, y, z, w])


def _quat_multiply_xyzw(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    """
    Multiply two quaternions in [x, y, z, w] format: result = q1 * q2.

    Args:
        q1: (4,) quaternion [x, y, z, w].
        q2: (4,) quaternion [x, y, z, w].

    Returns:
        (4,) product quaternion [x, y, z, w].
    """
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    ])


def _quat_multiply_batch_xyzw(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    """
    Multiply quaternion q1 with a batch of quaternions q2, all in [x, y, z, w].

    Args:
        q1: (4,) single quaternion [x, y, z, w].
        q2: (N, 4) batch of quaternions [x, y, z, w].

    Returns:
        (N, 4) product quaternions [x, y, z, w].
    """
    x1, y1, z1, w1 = q1
    x2 = q2[:, 0]
    y2 = q2[:, 1]
    z2 = q2[:, 2]
    w2 = q2[:, 3]
    return np.column_stack([
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    ])


# ============================================================================
# Public orientation transform functions
# ============================================================================

def transform_orientation(
    orientation_xyzw: np.ndarray,
    rotation_3x3: np.ndarray
) -> np.ndarray:
    """
    Apply a rotation to an orientation quaternion: q' = R_quat * q.

    The rotation from the 3x3 matrix is composed with the existing orientation
    via quaternion multiplication.

    Args:
        orientation_xyzw: (4,) quaternion in [x, y, z, w] format.
        rotation_3x3: (3, 3) rotation matrix to apply.

    Returns:
        (4,) transformed quaternion in [x, y, z, w] format as float32.
    """
    rot_quat = _rotation_matrix_to_quat_xyzw(rotation_3x3)
    result = _quat_multiply_xyzw(rot_quat, orientation_xyzw)
    return result.astype(np.float32)


def transform_orientations_batch(
    orientations_xyzw: np.ndarray,
    rotation_3x3: np.ndarray
) -> np.ndarray:
    """
    Apply a rotation to a batch of orientation quaternions: q' = R_quat * q.

    Args:
        orientations_xyzw: (N, 4) quaternions in [x, y, z, w] format.
        rotation_3x3: (3, 3) rotation matrix to apply.

    Returns:
        (N, 4) transformed quaternions in [x, y, z, w] format as float32.
    """
    rot_quat = _rotation_matrix_to_quat_xyzw(rotation_3x3)
    result = _quat_multiply_batch_xyzw(rot_quat, orientations_xyzw)
    return result.astype(np.float32)
