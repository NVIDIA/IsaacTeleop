# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""SO-101 wrist retargeter for the absolute-pose XR teleop pipeline.

The SO-101's task-space IK is position-only (it cannot track a full 6-DOF pose with a 5-DOF
arm), so the controller's roll and pitch about its grip axis are otherwise lost. This module
recovers both as dedicated joint channels: :class:`SO101WristRetargeter` reads the XR controller
grip orientation and emits:

* An **engage-relative** roll [rad] about the controller's own **local Z** axis
  (:data:`_APPROACH_AXIS`), forwarded to the ``wrist_roll`` joint.
* An **absolute world-elevation** pitch [rad] of the controller's **aim ray** (the AIM pose
  OpenXR provides, not the GRIP pose) above the horizontal plane
  (:func:`_approach_elevation`), forwarded to the position+pitch IK pitch channel.

Roll frame rationale: the roll is the swing-twist twist of the orientation delta *since engage*
(``R_engage^-1 . R_current``) about the grip's local Z axis (see :func:`_roll_twist`). Measuring
the delta about the grip's own axis -- rather than an absolute twist about a fixed world axis --
isolates wrist roll from hand pitch/yaw: rotations about axes perpendicular to local Z fall into
the (discarded) swing component, so ordinary heading/wobble does not leak into the channel. An
earlier revision took the absolute twist about fixed world Z, which cross-coupled controller yaw
(and, at non-vertical grasps, pitch) into the roll with gain ~1 -- hence over-sensitive control.

Pitch rationale: the pitch is taken from the controller's AIM ray (where the operator is
pointing), not the GRIP pose, because the ray elevation is the more intuitive handle for the
gripper's in-plane tilt. It is deliberately absolute (not engage-relative) -- the same ray
elevation always commands the same wrist tilt, regardless of when teleop engaged or from where
(e.g. pointing 45° down always tilts the gripper to 45°). Engage-relative pitch would require
the operator to mentally track the engage orientation, which is not natural.

Like the clutch, the roll channel keeps a running baseline: a plain Stop freezes the last
commanded roll and the next Play resumes from it (re-latching the reference orientation, so no
jump); an explicit reset re-zeros it to :data:`_WRIST_ROLL_OFFSET_RAD`. The pitch channel holds
its last value on a dropped frame and resets to :data:`_PITCH_OFFSET_RAD`.

The twist is computed by quaternion-projection swing-twist decomposition (see
:func:`_swing_twist_angle`), which stays well-conditioned near a 180-degree rotation where
Euler/rotvec extraction would be unstable.
"""

import numpy as np
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.execution_events import ExecutionState
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
    FloatType,
)

# Single source of truth for the stringly-typed pipeline wiring. These mirror the gripper
# node's ``gripper_command`` / ``gripper_value`` convention so the group/connect key and the
# flattened element label / ``output_order`` label stay structurally consistent.
ROLL_COMMAND_KEY = "roll_command"
"""Group / ``connect`` / ``input_config`` key for the roll channel."""
ROLL_ELEMENT_LABEL = "roll_value"
"""Flattened element label, used in the reorderer ``input_config`` value and ``output_order``."""

PITCH_COMMAND_KEY = "pitch_command"
"""Group / ``connect`` / ``input_config`` key for the pitch channel."""
PITCH_ELEMENT_LABEL = "pitch_value"
"""Flattened element label, used in the reorderer ``input_config`` value and ``output_order``."""

# The controller's local roll axis: wrist roll is the rotation about the grip's own Z axis
# (the OpenXR controller local Z). The roll is the twist of the orientation delta since engage
# about this axis, so it is expressed in the grip body frame -- not a fixed world axis -- which
# isolates roll from hand pitch/yaw. TODO(verify-in-sim): confirm local Z is the operator's
# intuitive roll axis for the grip pose convention in use.
_APPROACH_AXIS = np.array([0.0, 0.0, 1.0], dtype=np.float64)
# Controller-twist -> wrist_roll handedness. PhysX bounds the joint at its hard USD limit; a
# guessed node-side clamp would mask sign/scale bugs during bring-up, so none is applied.
_ROLL_SIGN = 1.0  # TODO(verify-in-sim)
# Calibration zero [rad]. Flipped 180 deg so the engaged wrist_roll seed is pi rather than 0
# (the gripper's neutral roll faces the opposite way from the SO-101 joint zero). TODO(tune-in-sim)
_WRIST_ROLL_OFFSET_RAD = np.pi

# Local axis whose world elevation defines the commanded pitch. Pitch is read from the
# controller's AIM pose -- the pointer ray that OpenXR already provides -- not the GRIP pose,
# so no grip->ray offset is computed here. The SO-101 pitch is an ABSOLUTE world elevation (not
# engage-relative). Distinct from _APPROACH_AXIS (the grip-local +Z twist axis used for roll).
# TODO(verify-in-sim): confirm the sign for the aim pose convention (flip _PITCH_SIGN if needed).
_PITCH_APPROACH_AXIS = np.array([0.0, 0.0, 1.0], dtype=np.float64)
_PITCH_SIGN = 1.0  # TODO(verify-in-sim)
# TODO(tune-in-sim): absolute elevation that maps to the home tilt
_PITCH_OFFSET_RAD = 0.0


def _swing_twist_angle(quat_xyzw: np.ndarray, axis: np.ndarray) -> float:
    """Return the swing-twist twist angle [rad] of a quaternion about an axis.

    Uses quaternion-projection swing-twist decomposition: the twist component is the part of
    the rotation about ``axis``, and its angle is ``2 * atan2(d, w)`` where ``d`` is the
    projection of the vector part onto ``axis`` and ``w`` is the scalar part. This is robust
    near a 180-degree rotation, unlike Euler/rotvec extraction.

    Args:
        quat_xyzw: Unit quaternion in ``[x, y, z, w]`` (scipy) order, shape ``(4,)``.
        axis: Unit twist axis in the quaternion's frame, shape ``(3,)``.

    Returns:
        The twist angle [rad] in ``(-pi, pi]``; ``0.0`` when the twist is degenerate.
    """
    q = np.asarray(quat_xyzw, dtype=np.float64)
    # Hemisphere-canonicalize so the twist angle has a consistent sign.
    if q[3] < 0.0:
        q = -q
    w = q[3]
    d = float(np.dot(q[:3], axis))
    # Degeneracy guard: a pure 180-degree swing leaves no twist component to recover.
    if w * w + d * d < 1e-12:
        return 0.0
    return 2.0 * np.arctan2(d, w)


def _quat_conj(q: np.ndarray) -> np.ndarray:
    """Conjugate (inverse, for a unit quaternion) of an ``[x, y, z, w]`` quaternion."""
    return np.array([-q[0], -q[1], -q[2], q[3]], dtype=np.float64)


def _quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product ``a (x) b`` of two ``[x, y, z, w]`` quaternions (scalar-last).

    Matches the SciPy ``Rotation`` composition convention: ``(Ra * Rb).as_quat()`` equals
    ``_quat_mul(Ra.as_quat(), Rb.as_quat())``.
    """
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array(
        [
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        ],
        dtype=np.float64,
    )


def _roll_twist(
    ref_quat_xyzw: np.ndarray, cur_quat_xyzw: np.ndarray, axis: np.ndarray
) -> float:
    """Return the roll [rad] of ``cur`` relative to ``ref`` about a grip-local ``axis``.

    Computes the orientation delta since the reference (``ref^-1 . cur``, expressed in the
    reference's body frame) and takes its swing-twist twist about ``axis`` (the grip local roll
    axis). Rotations about axes perpendicular to ``axis`` fall into the discarded swing, so hand
    pitch/yaw do not leak into the roll. With an identity ``ref`` this reduces to the absolute
    swing-twist of ``cur`` about ``axis``.

    Args:
        ref_quat_xyzw: Reference (engage) grip orientation, unit quaternion ``[x, y, z, w]``.
        cur_quat_xyzw: Current grip orientation, unit quaternion ``[x, y, z, w]``.
        axis: Grip-local roll axis, shape ``(3,)``.

    Returns:
        The relative roll angle [rad] in ``(-pi, pi]``.
    """
    ref = np.asarray(ref_quat_xyzw, dtype=np.float64)
    cur = np.asarray(cur_quat_xyzw, dtype=np.float64)
    delta = _quat_mul(_quat_conj(ref), cur)
    return _swing_twist_angle(delta, axis)


def _approach_elevation(quat_xyzw: np.ndarray) -> float:
    """Return the elevation [rad] of the pose approach axis above the world horizontal plane.

    Rotates :data:`_PITCH_APPROACH_AXIS` by the given orientation (the controller AIM pose) and
    returns ``atan2(z, ||xy||)`` of the result -- the signed angle above horizontal, in
    ``[-pi/2, pi/2]``. This is an absolute (not engage-relative) measure: the same orientation
    always yields the same elevation, independent of azimuth.

    Args:
        quat_xyzw: Unit AIM-pose quaternion in ``[x, y, z, w]`` (scipy) order, shape ``(4,)``.

    Returns:
        The approach-axis elevation [rad] above world horizontal.
    """
    q = np.asarray(quat_xyzw, dtype=np.float64)
    a = _PITCH_APPROACH_AXIS
    av = np.array([a[0], a[1], a[2], 0.0], dtype=np.float64)
    rotated = _quat_mul(_quat_mul(q, av), _quat_conj(q))[:3]
    horiz = float(np.hypot(rotated[0], rotated[1]))
    return float(np.arctan2(rotated[2], horiz))


class SO101WristRetargeter(BaseRetargeter):
    """Retargets XR controller grip orientation to SO-101 wrist-roll and wrist-pitch commands.

    Reads the grip orientation of one controller and emits two channels:

    * **Roll** (engage-relative): the swing-twist twist [rad] of ``R_engage^-1 . R_current``
      about the grip's own local Z axis (:data:`_APPROACH_AXIS`, see :func:`_roll_twist`),
      offset by :data:`_WRIST_ROLL_OFFSET_RAD` and signed by :data:`_ROLL_SIGN`. Measuring the
      delta about the grip's own axis isolates wrist roll from hand pitch/yaw (those fall into
      the discarded swing). Like the clutch, the channel keeps a running baseline: the reference
      orientation is latched on the first RUNNING frame and re-armed whenever teleop is not
      RUNNING, so each Play resumes from the last commanded roll without a jump. A reset
      re-zeros the roll to the offset.

    * **Pitch** (absolute): the world elevation [rad] of the controller's AIM ray
      (:func:`_approach_elevation`), signed by :data:`_PITCH_SIGN` and offset by
      :data:`_PITCH_OFFSET_RAD`. Taken from the AIM pose (pointer), not the GRIP pose. The same
      aim orientation always commands the same pitch, independent of when teleop engaged or the
      azimuth of the controller. The last value is held on a dropped/aim-invalid frame, and
      reset to the offset.

    Outputs floats under :data:`ROLL_COMMAND_KEY` / :data:`ROLL_ELEMENT_LABEL` and
    :data:`PITCH_COMMAND_KEY` / :data:`PITCH_ELEMENT_LABEL`.
    """

    def __init__(self, name: str, input_device: str = ControllersSource.RIGHT) -> None:
        """Initialize the wrist retargeter.

        Args:
            name: Name identifier for this retargeter node.
            input_device: Controller source key to read the grip orientation from.
        """
        self._input_device = input_device
        super().__init__(name=name)
        # Reference grip orientation latched on engage (``[x, y, z, w]``), or ``None`` when
        # re-armed (not yet engaged this episode / after a Stop or reset).
        self._ref_quat: np.ndarray | None = None
        # Running roll baseline [rad], latched on engage to the last commanded roll so a re-clutch
        # resumes there. Re-zeroed to the offset on reset.
        self._roll_baseline = _WRIST_ROLL_OFFSET_RAD
        self._last_roll = _WRIST_ROLL_OFFSET_RAD
        # Last commanded pitch [rad]; held on dropped frames and reset to offset.
        self._last_pitch = _PITCH_OFFSET_RAD

    def input_spec(self) -> RetargeterIOType:
        """Requires the grip orientation of the configured controller (Optional)."""
        return {self._input_device: OptionalType(ControllerInput())}

    def output_spec(self) -> RetargeterIOType:
        """Outputs engage-relative wrist-roll and absolute wrist-pitch [rad] under ``ROLL_COMMAND_KEY`` / ``PITCH_COMMAND_KEY``."""
        return {
            ROLL_COMMAND_KEY: TensorGroupType(
                ROLL_COMMAND_KEY, [FloatType(ROLL_ELEMENT_LABEL)]
            ),
            PITCH_COMMAND_KEY: TensorGroupType(
                PITCH_COMMAND_KEY, [FloatType(PITCH_ELEMENT_LABEL)]
            ),
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Computes engage-relative roll and absolute pitch [rad]; holds last on a dropped frame."""
        running = context.execution_events.execution_state == ExecutionState.RUNNING

        if context.execution_events.reset:
            # Fresh episode: re-arm the reference, re-zero roll to the offset, reset pitch.
            self._ref_quat = None
            self._last_roll = _WRIST_ROLL_OFFSET_RAD
            self._last_pitch = _PITCH_OFFSET_RAD
        elif not running:
            # A plain Stop re-arms the reference but FREEZES the running roll, so the next Play
            # resumes from the last commanded value.
            self._ref_quat = None

        roll_out = outputs[ROLL_COMMAND_KEY]
        pitch_out = outputs[PITCH_COMMAND_KEY]
        inp = inputs[self._input_device]

        if inp.is_none:
            # Dropped frame: hold the last commanded values for both channels.
            roll_out[0] = self._last_roll
            pitch_out[0] = self._last_pitch
            return

        quat_xyzw = np.from_dlpack(inp[ControllerInputIndex.GRIP_ORIENTATION]).astype(
            np.float64
        )  # XYZW

        if self._ref_quat is None:
            if not running:
                # Connected but not playing yet: hold the last values and do not latch the reference.
                roll_out[0] = self._last_roll
                pitch_out[0] = self._last_pitch
                return
            # First RUNNING frame (Play just started): latch the reference orientation and the
            # running baseline (the last commanded roll) so the channel resumes without a jump.
            self._ref_quat = quat_xyzw.copy()
            self._roll_baseline = self._last_roll

        self._last_roll = self._roll_baseline + _ROLL_SIGN * _roll_twist(
            self._ref_quat, quat_xyzw, _APPROACH_AXIS
        )
        roll_out[0] = self._last_roll

        # Pitch is computed from the AIM pose (pointer ray), not the GRIP pose. Hold the last
        # pitch if the aim pose is not tracked this frame.
        if bool(inp[ControllerInputIndex.AIM_IS_VALID]):
            aim_quat_xyzw = np.from_dlpack(
                inp[ControllerInputIndex.AIM_ORIENTATION]
            ).astype(np.float64)  # XYZW
            self._last_pitch = (
                _PITCH_SIGN * _approach_elevation(aim_quat_xyzw) + _PITCH_OFFSET_RAD
            )
        pitch_out[0] = self._last_pitch


# Back-compat alias: the class was formerly named SO101RollRetargeter.
SO101RollRetargeter = SO101WristRetargeter
