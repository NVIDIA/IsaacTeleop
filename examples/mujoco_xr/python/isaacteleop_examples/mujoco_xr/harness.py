# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The safety harness the ghost renders, and the signal that it intervened.

``EePoseRateLimiter`` is a three-band governor -- pass-through, clamped, refused -- and
the ghost renders its *output*, so an intervention already shows as the tool lagging
the hand. A lag alone does not say which band, so :class:`InterventionMonitor` recovers
it by comparing what the limiter was given against what it emitted, and recolours the
ghost. Colour goes on the shared ``leader_ghost`` material rather than per geom.
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


class HandPose(enum.Enum):
    """Which standard OpenXR controller pose the app drives from.

    Different frames for different jobs, per the OpenXR spec. Grip is the palm centroid,
    for rendering a held object; its -Z runs little finger to thumb, through the fist,
    and is not a pointing direction. Aim's -Z is the pointing ray. A facing read off grip
    therefore turns 1:1 with the hand but has an arbitrary zero.
    """

    GRIP = "grip"
    AIM = "aim"

    @property
    def indices(self) -> tuple[int, int, int]:
        """``(position, orientation, is_valid)`` in ``ControllerInput`` for this pose."""
        if self is HandPose.GRIP:
            return (
                ControllerInputIndex.GRIP_POSITION,
                ControllerInputIndex.GRIP_ORIENTATION,
                ControllerInputIndex.GRIP_IS_VALID,
            )
        return (
            ControllerInputIndex.AIM_POSITION,
            ControllerInputIndex.AIM_ORIENTATION,
            ControllerInputIndex.AIM_IS_VALID,
        )


def _pose_type() -> TensorGroupType:
    """The 7-D ``[x, y, z, qx, qy, qz, qw]`` contract EePoseRateLimiter governs."""
    return TensorGroupType(
        EE_POSE_KEY,
        [NDArrayType("pose", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32)],
    )


class ControllerPoseSource(BaseRetargeter):
    """One controller pose, repacked as the 7-D ``ee_pose`` the limiter takes.

    Emits in the XR reference frame; ``mj_from_xr`` is rigid, so limiting here and
    transforming afterwards bounds the same metres and radians. Goes absent on an invalid
    pose rather than holding the last one, which is the limiter's job. Everything
    downstream consumes this output, so :class:`HandPose` switches the whole app at once.
    """

    def __init__(
        self,
        name: str,
        pose: HandPose = HandPose.GRIP,
        input_device: str = ControllersSource.RIGHT,
    ) -> None:
        """Initialize the controller-pose adapter.

        Args:
            name: Name identifier for this retargeter node.
            pose: Which OpenXR controller pose to read.
            input_device: Controller source key to read the pose from.
        """
        self._input_device = input_device
        self._pose = pose
        super().__init__(name=name)

    @property
    def pose(self) -> HandPose:
        """Which OpenXR controller pose this emits."""
        return self._pose

    def input_spec(self) -> RetargeterIOType:
        """Requires the configured controller (Optional)."""
        return {self._input_device: OptionalType(ControllerInput())}

    def output_spec(self) -> RetargeterIOType:
        """Outputs an Optional absolute 7-D ``ee_pose``."""
        return {EE_POSE_KEY: OptionalType(_pose_type())}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Repacks the pose; goes absent when the controller is untracked."""
        out = outputs[EE_POSE_KEY]
        inp = inputs[self._input_device]
        position_index, orientation_index, valid_index = self._pose.indices
        if inp.is_none or not bool(inp[valid_index]):
            out.set_none()
            return

        position = inp[position_index]
        orientation = inp[orientation_index]
        # Both orientations are already (x, y, z, w), the limiter's convention.
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


# Above the float32 round-trip and quaternion-recomposition floor (~1e-7), far below
# anything an operator could see. A band decided by numerical noise would strobe the
# ghost every frame.
_POS_EPS_M = 1e-4
_ANG_EPS_RAD = 1e-3


def _moved(a: np.ndarray, b: np.ndarray) -> bool:
    """True when two 7-D poses differ by more than the noise floor.

    Double-cover aware on the quaternion: the two signs are the same rotation.
    """
    dot = min(1.0, abs(float(np.dot(a[3:7], b[3:7]))))
    return (
        float(np.linalg.norm(a[:3] - b[:3])) > _POS_EPS_M
        or 2.0 * float(np.arccos(dot)) > _ANG_EPS_RAD
    )


def classify(
    given: np.ndarray, emitted: np.ndarray, previous: np.ndarray | None
) -> HarnessBand:
    """The band, from the pose the limiter was given and the one it emitted.

    Reading it off the poses keeps the limiter unmodified and works for any governor
    with the same contract.

    Args:
        given: The 7-D pose handed to the limiter this frame.
        emitted: The 7-D pose it produced.
        previous: The pose it produced last frame, or None on the first.
    """
    if not _moved(given, emitted):
        return HarnessBand.PASS_THROUGH
    # Emitted nothing new while the input moved away: refused, not approached. A clamp
    # always closes some of the gap, so it cannot land here.
    if previous is not None and not _moved(emitted, previous):
        return HarnessBand.REJECTED
    return HarnessBand.CLAMPED


# rgb only: the authored alpha is kept, because the ghost is opaque by design (see
# assets/leader/leader_gripper.xml).
_BAND_RGB = {
    HarnessBand.CLAMPED: (1.00, 0.72, 0.20),
    HarnessBand.REJECTED: (1.00, 0.25, 0.20),
}


class InterventionMonitor:
    """Classifies each governed frame and recolours the ghost to match.

    Holds the previous emitted pose, which is what separates a refused frame from a
    clamped one, and counts the bands so a session can be summarised afterwards.
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

    def update(
        self, model, given: np.ndarray, emitted: np.ndarray, *, paint: bool = True
    ) -> HarnessBand:
        """Classify this frame, advance the baseline, and (unless told not to) paint.

        Classification runs on every governed frame even while the ghost is hidden: a
        gap in the baseline would misclassify the frame the ghost reappears on.
        """
        band = classify(given, emitted, self._previous)
        self._previous = np.array(emitted, dtype=np.float64)
        self.counts[band] += 1

        if paint:
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
