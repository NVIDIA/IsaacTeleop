# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""XR to scene-world coordinates, and the near-plane projection, from the backend.

Re-exported rather than reimplemented so ``cpp/frames.hpp`` and ``cpp/glcamera.hpp`` stay
the one definition of each.

.. warning::
   :data:`TRANS_MJ_FROM_XR` is a calibration compiled into the wheel, not a convention: its
   ``x`` is how far in front of the operator the scene's origin sits and its ``z`` a floor
   datum, both authored for one example's workspace. Only static scene content sees it.
   Make it a :class:`~isaacteleop.viz.robot.SceneTwin` argument before a second consumer
   relies on it.
"""

from __future__ import annotations

import numpy as np

from . import _robot_twin
from .quaternion import conjugate, multiply, rotate

#: Rotation from XR reference space (Y-up, -Z forward) to scene world (Z-up), wxyz.
QUAT_MJ_FROM_XR = _robot_twin.QUAT_MJ_FROM_XR
#: Workspace translation applied after that rotation. See the module warning.
TRANS_MJ_FROM_XR = _robot_twin.TRANS_MJ_FROM_XR

#: XR reference-space point (metres, Y-up) -> scene world point (Z-up). Applies both the
#: handedness rotation and the workspace translation.
mj_from_xr_pos = _robot_twin.mj_from_xr_pos
#: XR orientation as xyzw -> scene world orientation as wxyz.
mj_from_xr_quat = _robot_twin.mj_from_xr_quat

#: The camera frustum for one asymmetric fov, as
#: ``(center, half_width, bottom, top, near, far)``. The renderer's own code path,
#: exposed so the convention is testable without a GPU.
frustum_from_fov = _robot_twin.frustum_from_fov
#: What a view-space distance becomes in the depth buffer handed to
#: ``ProjectionLayer.submit()``: standard Z, near -> 0, far -> 1.
submitted_depth = _robot_twin.submitted_depth


def xr_from_mj_pos(p_mj) -> np.ndarray:
    """Scene world point -> XR reference-space point. Inverse of :func:`mj_from_xr_pos`,
    derived from the same two exported constants.
    """
    inverse = conjugate(np.array(QUAT_MJ_FROM_XR, dtype=float))
    return rotate(np.asarray(p_mj, dtype=float) - np.array(TRANS_MJ_FROM_XR), inverse)


def xr_from_mj_quat(q_wxyz) -> np.ndarray:
    """Scene world orientation (wxyz) -> XR orientation as xyzw."""
    inverse = conjugate(np.array(QUAT_MJ_FROM_XR, dtype=float))
    q_xr = multiply(inverse, np.asarray(q_wxyz, dtype=float))
    return np.array([q_xr[1], q_xr[2], q_xr[3], q_xr[0]])


def mj_from_xr_rotation(q_xr_wxyz) -> np.ndarray:
    """An XR-frame rotation expressed in the scene: ``Q q Q^-1``, wxyz throughout.

    Not :func:`mj_from_xr_quat`, which maps a body's orientation across the frames as a
    single left-multiply. XR +Y is scene +z, so an XR yaw of theta comes out as a scene
    rotation of theta about +z.
    """
    q_frame = np.array(QUAT_MJ_FROM_XR, dtype=float)
    return multiply(
        multiply(q_frame, np.asarray(q_xr_wxyz, dtype=float)), conjugate(q_frame)
    )


__all__ = [
    "QUAT_MJ_FROM_XR",
    "TRANS_MJ_FROM_XR",
    "frustum_from_fov",
    "mj_from_xr_pos",
    "mj_from_xr_quat",
    "mj_from_xr_rotation",
    "submitted_depth",
    "xr_from_mj_pos",
    "xr_from_mj_quat",
]
