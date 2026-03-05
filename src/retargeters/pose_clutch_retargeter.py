# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
PoseClutchRetargeter — outputs an accumulated SE3 clutch-offset transform.

When teleop is paused and the user moves their hand/controller to a new
position before resuming, the output pose would jump discontinuously. This
retargeter solves that by computing and accumulating an SE3 offset each time
the session resumes, so downstream retargeters can pre-compose the offset and
produce a seamless, continuous output.

Supported input formats
-----------------------
Wire exactly ONE of the two optional input ports:

    input_pose  — (7,) float32 [x, y, z, qx, qy, qz, qw]
                  Wired from Se3AbsRetargeter.output("ee_pose") or any node
                  that produces the standard 7-element EE pose.

    head_pose   — HeadPose TensorGroup (position (3,) + orientation (4,) + valid)
                  Wired directly from HeadSource.output("head_pose") with no
                  adapter needed.

Output
------
    clutch_transform — TransformMatrix (4×4 float32)
        The accumulated clutch offset.  Identity when no clutch is active.
        Apply left-multiply in downstream retargeters:
            T_effective = T_clutch @ T_input

Lifecycle
---------
- STOP / START : clutch resets to identity (pass-through mode).
- PAUSE        : records the current raw input pose as the "freeze point".
- RESUME       : computes T_delta = T_pause_in @ inv(T_resume_in) and
                 accumulates: T_clutch_new = T_clutch_old @ T_delta
                 After this, T_clutch_new @ T_resume_in = T_clutch_old @ T_pause_in
                 (seamless continuity).
- All other frames: output T_clutch unchanged.

Multiple pause/resume cycles accumulate correctly:

    T_clutch₂ @ T_resume₂ = T_clutch₁ @ T_pause₂

Examples
--------
From Se3AbsRetargeter::

    clutch = PoseClutchRetargeter("clutch").connect({
        "input_pose": se3.output("ee_pose"),
    })

From HeadSource directly (no adapter)::

    head    = HeadSource("head")
    clutch  = PoseClutchRetargeter("clutch").connect({
        "head_pose": head.output("head_pose"),
    })
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from scipy.spatial.transform import Rotation

from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import ComputeContext, RetargeterIO, RetargeterIOType
from ..interface.teleop_events import TeleopRunEvent
from ..interface.tensor_group_type import OptionalType
from ..tensor_types import NDArrayType, DLDataType, TransformMatrix, HeadPose, HeadPoseIndex
from ..tensor_types.tensor_group_type import TensorGroupType


# ============================================================================
# Helpers
# ============================================================================


def _pose7_to_mat4(pose: np.ndarray) -> np.ndarray:
    """Convert [x, y, z, qx, qy, qz, qw] to a 4×4 float32 homogeneous matrix."""
    mat = np.eye(4, dtype=np.float32)
    mat[:3, :3] = Rotation.from_quat(pose[3:7]).as_matrix().astype(np.float32)
    mat[:3, 3] = pose[:3].astype(np.float32)
    return mat


def _posquat_to_mat4(position: np.ndarray, quaternion: np.ndarray) -> np.ndarray:
    """Convert separate position (3,) and quaternion (4, xyzw) to a 4×4 float32 matrix."""
    mat = np.eye(4, dtype=np.float32)
    mat[:3, :3] = Rotation.from_quat(quaternion).as_matrix().astype(np.float32)
    mat[:3, 3] = position.astype(np.float32)
    return mat


def _mat4_inv(mat: np.ndarray) -> np.ndarray:
    """Analytically invert a rigid-body 4×4 homogeneous transform.

    For [R | p; 0 | 1]:  inv = [R^T | -R^T p; 0 | 1]
    """
    inv = np.eye(4, dtype=np.float32)
    R = mat[:3, :3]
    p = mat[:3, 3]
    inv[:3, :3] = R.T
    inv[:3, 3] = -(R.T @ p)
    return inv


# ============================================================================
# PoseClutchRetargeter
# ============================================================================


def _ee_pose_type() -> TensorGroupType:
    """Type matching the output of Se3AbsRetargeter: 7-element float32 pose."""
    return TensorGroupType(
        "ee_pose",
        [NDArrayType("pose", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32)],
    )


class PoseClutchRetargeter(BaseRetargeter):
    """Accumulates SE3 clutch offsets and outputs a 4×4 TransformMatrix.

    See module docstring for full details.
    """

    def __init__(self, name: str) -> None:
        self._T_clutch: np.ndarray = np.eye(4, dtype=np.float32)
        self._T_pause_in: Optional[np.ndarray] = None  # 4×4 recorded at PAUSE
        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        return {
            # 7D pose from Se3AbsRetargeter or any EE pose source
            "input_pose": OptionalType(_ee_pose_type()),
            # Head tracker pose — accepted directly, no adapter needed
            "head_pose": OptionalType(HeadPose()),
        }

    def output_spec(self) -> RetargeterIOType:
        return {
            "clutch_transform": TransformMatrix(),
        }

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _reset(self) -> None:
        self._T_clutch = np.eye(4, dtype=np.float32)
        self._T_pause_in = None

    def _read_mat4(self, inputs: RetargeterIO) -> Optional[np.ndarray]:
        """Read whichever pose input is connected and convert to a 4×4 matrix.

        Tries input_pose first, then head_pose.  Returns None if both are absent.
        """
        tg = inputs.get("input_pose")
        if tg is not None and not tg.is_none:
            pose = np.asarray(tg[0]).astype(np.float32)
            return _pose7_to_mat4(pose)

        tg = inputs.get("head_pose")
        if tg is not None and not tg.is_none:
            position = np.asarray(tg[HeadPoseIndex.POSITION]).astype(np.float32)
            orientation = np.asarray(tg[HeadPoseIndex.ORIENTATION]).astype(np.float32)
            return _posquat_to_mat4(position, orientation)

        return None

    # ------------------------------------------------------------------ #
    # Compute                                                              #
    # ------------------------------------------------------------------ #

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        ev = context.run_event

        if ev in (TeleopRunEvent.STOP, TeleopRunEvent.START):
            self._reset()

        elif ev == TeleopRunEvent.PAUSE:
            T_in = self._read_mat4(inputs)
            if T_in is not None:
                self._T_pause_in = T_in

        elif ev == TeleopRunEvent.RESUME:
            if self._T_pause_in is not None:
                T_in = self._read_mat4(inputs)
                if T_in is not None:
                    # T_delta = T_pause_in @ inv(T_resume_in)
                    # ensures T_clutch_new @ T_resume_in = T_clutch_old @ T_pause_in
                    T_delta = self._T_pause_in @ _mat4_inv(T_in)
                    self._T_clutch = self._T_clutch @ T_delta
                    self._T_pause_in = None  # consumed

        # Always output the current clutch transform (identity = pass-through)
        outputs["clutch_transform"][0] = self._T_clutch.copy()
