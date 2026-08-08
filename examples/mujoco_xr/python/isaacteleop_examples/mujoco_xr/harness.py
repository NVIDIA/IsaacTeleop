# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The safety harness the ghost renders, and the signal that it intervened.

``EePoseRateLimiter`` is a three-band governor: motion under the limits is
emitted untouched, motion over them is clamped to the limit, and a frame whose
input velocity breaks the reject envelope is refused outright. The ghost renders
its *output*, so an intervention is already visible as the tool ceasing to track
the hand -- but a lag alone does not say which band, or whether the harness acted
at all. :class:`InterventionMonitor` recovers the band by comparing what the
limiter was given against what it emitted, and recolours the ghost.

Colour is carried on the shared ``leader_ghost`` material rather than per geom:
one write recolours the whole tool, and ``geom_rgba`` would silently win over the
material if it were ever set away from its default.
"""

from __future__ import annotations

import enum

import mujoco
import numpy as np
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import BaseRetargeter, RetargeterIOType
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
    DLDataType,
    NDArrayType,
)
from isaacteleop.retargeters.rate_limiter import EE_POSE_KEY

# The material every ghost geom in assets/leader/leader_gripper.xml carries.
GHOST_MATERIAL = "leader_ghost"


def _pose_type() -> TensorGroupType:
    """The 7-D ``[x, y, z, qx, qy, qz, qw]`` contract EePoseRateLimiter governs."""
    return TensorGroupType(
        EE_POSE_KEY,
        [NDArrayType("pose", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32)],
    )


class GripPoseSource(BaseRetargeter):
    """One controller's grip pose, repacked as the 7-D ``ee_pose`` the limiter takes.

    Emits in the XR reference frame; ``mj_from_xr`` is rigid, so limiting here and
    transforming afterwards bounds the same metres and radians.

    The output is Optional and goes absent on an invalid grip rather than holding
    the last pose. Hold-last is the limiter's job, and leaving it there keeps
    "never tracked yet" distinct from "tracked, then lost" -- an untracked grip
    reads as (0, 0, 0), which is a place a legitimate pose could put the ghost.
    """

    def __init__(self, name: str, input_device: str = ControllersSource.RIGHT) -> None:
        """Initialize the grip-pose adapter.

        Args:
            name: Name identifier for this retargeter node.
            input_device: Controller source key to read the grip pose from.
        """
        self._input_device = input_device
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        """Requires the grip pose of the configured controller (Optional)."""
        return {self._input_device: OptionalType(ControllerInput())}

    def output_spec(self) -> RetargeterIOType:
        """Outputs an Optional absolute 7-D ``ee_pose``."""
        return {EE_POSE_KEY: OptionalType(_pose_type())}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Repacks the grip pose; goes absent when the controller is untracked."""
        out = outputs[EE_POSE_KEY]
        inp = inputs[self._input_device]
        if inp.is_none or not bool(inp[ControllerInputIndex.GRIP_IS_VALID]):
            out.set_none()
            return

        position = inp[ControllerInputIndex.GRIP_POSITION]
        orientation = inp[ControllerInputIndex.GRIP_ORIENTATION]
        # GRIP_ORIENTATION is already (x, y, z, w), the limiter's convention.
        out[0] = np.array(
            [
                float(position[0]),
                float(position[1]),
                float(position[2]),
                float(orientation[0]),
                float(orientation[1]),
                float(orientation[2]),
                float(orientation[3]),
            ],
            dtype=np.float32,
        )


class HarnessBand(enum.Enum):
    """Which of the limiter's three bands produced the frame the ghost renders."""

    PASS_THROUGH = "pass-through"
    CLAMPED = "clamped"
    REJECTED = "rejected"


# Above the float32 round-trip and quaternion-recomposition floor (~1e-7), far
# below anything an operator could see. A band decided by numerical noise would
# strobe the ghost every frame.
_POS_EPS_M = 1e-4
_ANG_EPS_RAD = 1e-3


def _pose_delta(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Metres and radians between two 7-D poses; double-cover aware on the quaternion."""
    distance = float(np.linalg.norm(a[:3] - b[:3]))
    dot = min(1.0, abs(float(np.dot(a[3:7], b[3:7]))))
    return distance, 2.0 * float(np.arccos(dot))


def _moved(a: np.ndarray, b: np.ndarray) -> bool:
    """True when two poses differ by more than the noise floor."""
    distance, angle = _pose_delta(a, b)
    return distance > _POS_EPS_M or angle > _ANG_EPS_RAD


def classify(
    given: np.ndarray, emitted: np.ndarray, previous: np.ndarray | None
) -> HarnessBand:
    """The band, from the pose the limiter was given and the one it emitted.

    Reading the band off the poses keeps the limiter unmodified -- it reports no
    band of its own -- and works for any governor with the same contract.

    Args:
        given: The 7-D pose handed to the limiter this frame.
        emitted: The 7-D pose it produced.
        previous: The pose it produced last frame, or None on the first.
    """
    if not _moved(given, emitted):
        return HarnessBand.PASS_THROUGH
    # Emitted nothing new while the input moved away: the frame was refused, not
    # approached. A clamp always closes some of the gap, so it cannot land here.
    if previous is not None and not _moved(emitted, previous):
        return HarnessBand.REJECTED
    return HarnessBand.CLAMPED


# rgb only: the authored alpha is kept, because the ghost is opaque by design
# (see assets/leader/leader_gripper.xml -- alpha 1.0 is what keeps draw order
# free and the ghost out of CloudXR's reprojection buffer).
_BAND_RGB = {
    HarnessBand.CLAMPED: (1.00, 0.72, 0.20),
    HarnessBand.REJECTED: (1.00, 0.25, 0.20),
}


class InterventionMonitor:
    """Classifies each governed frame and recolours the ghost to match.

    Holds the previous emitted pose, which is what separates a refused frame from
    a clamped one, and counts both so a session can be summarised on the terminal
    afterwards -- the operator sees the colour, the log says how often.
    """

    def __init__(self, model) -> None:
        """Latch the authored ghost colour as the pass-through colour.

        Args:
            model: The compiled ``mjModel``; must declare :data:`GHOST_MATERIAL`.
        """
        self._mat = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_MATERIAL, GHOST_MATERIAL
        )
        if self._mat < 0:
            raise RuntimeError(
                f"mujoco_xr: the scene declares no `{GHOST_MATERIAL}` material; "
                "the ghost cannot report harness interventions."
            )
        self._rgba = np.array(model.mat_rgba[self._mat], dtype=np.float64)
        self._previous: np.ndarray | None = None
        self.counts = dict.fromkeys(HarnessBand, 0)

    @property
    def pass_through_rgba(self) -> np.ndarray:
        """The authored ghost colour, restored whenever the harness is not acting."""
        return self._rgba.copy()

    def update(self, model, given: np.ndarray, emitted: np.ndarray) -> HarnessBand:
        """Classify this frame, paint the ghost, and advance the baseline."""
        band = classify(given, emitted, self._previous)
        self._previous = np.array(emitted, dtype=np.float64)
        self.counts[band] += 1

        rgba = self._rgba.copy()
        if band in _BAND_RGB:
            rgba[:3] = _BAND_RGB[band]
        model.mat_rgba[self._mat] = rgba
        return band

    def summary(self) -> str:
        """One line: how much of the session the harness spent intervening."""
        total = sum(self.counts.values())
        if total == 0:
            return "harness: no governed frames"
        return "harness: {} frames -- {} clamped, {} rejected".format(
            total,
            self.counts[HarnessBand.CLAMPED],
            self.counts[HarnessBand.REJECTED],
        )
