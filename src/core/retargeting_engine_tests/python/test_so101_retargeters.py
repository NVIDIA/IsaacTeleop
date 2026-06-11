# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Sim-free unit tests for the SO-101 XR teleop retargeters.

Covers the SO-101 retargeters that drive the position-only IK stacking pipeline:

* :class:`~isaacteleop.retargeters.SO101GripperRetargeter` -- analog trigger -> jaw closedness.
* :class:`~isaacteleop.retargeters.SO101WristRetargeter` -- grip roll -> absolute wrist-roll
  angle via swing-twist decomposition, plus absolute world-elevation pitch.
* :class:`~isaacteleop.retargeters.SO101ClutchRetargeter` -- clutch-rebased absolute EE pose.

Each retargeter is exercised both at the pure-math level (the module-private helper functions)
and at the ``BaseRetargeter.compute`` level (build inputs/outputs, drive a frame, read the
emitted tensor), with no ``gym.make``, USD, GPU, or XR device.
"""

import math

import numpy as np
import pytest

from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import (
    ComputeContext,
    ExecutionEvents,
    ExecutionState,
    OptionalTensorGroup,
    TensorGroup,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import GraphTime
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalTensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
)
from isaacteleop.retargeters import (
    SO101ClutchRetargeter,
    SO101GripperRetargeter,
    SO101RollRetargeter,
)
from isaacteleop.retargeters import SO101WristRetargeter
from isaacteleop.retargeters.SO101.clutch_retargeter import (
    _CLUTCH_HOME_EE_POS,
    _rebased_position,
)
from isaacteleop.retargeters.SO101.gripper_retargeter import (
    GRIPPER_COMMAND_KEY,
    _TRIGGER_DEADZONE,
    _trigger_to_closedness,
)
from isaacteleop.retargeters.SO101.wrist_retargeter import (
    PITCH_COMMAND_KEY,
    ROLL_COMMAND_KEY,
    _APPROACH_AXIS,
    _PITCH_APPROACH_AXIS,
    _approach_elevation,
    _roll_twist,
    _swing_twist_angle,
    _WRIST_ROLL_OFFSET_RAD,
)

# ---------------------------------------------------------------------------
# Helpers (mirror the patterns in test_sharpa_hand_retargeter.py)
# ---------------------------------------------------------------------------

_ID_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)


def _make_context(
    *, reset: bool = False, state: ExecutionState = ExecutionState.RUNNING
) -> ComputeContext:
    """Build a ComputeContext with the given reset flag and execution state."""
    return ComputeContext(
        graph_time=GraphTime(sim_time_ns=0, real_time_ns=0),
        execution_events=ExecutionEvents(reset=reset, execution_state=state),
    )


def _build_io(retargeter):
    """Construct empty input/output containers for a retargeter (optionals start absent)."""
    inputs = {}
    for k, v in retargeter.input_spec().items():
        inputs[k] = (
            OptionalTensorGroup(v)
            if isinstance(v, OptionalTensorGroupType)
            else TensorGroup(v)
        )
    outputs = {}
    for k, v in retargeter.output_spec().items():
        outputs[k] = (
            OptionalTensorGroup(v)
            if isinstance(v, OptionalTensorGroupType)
            else TensorGroup(v)
        )
    return inputs, outputs


def _make_controller(
    *,
    grip_pos=(0.0, 0.0, 0.0),
    grip_ori=_ID_QUAT,
    aim_ori=_ID_QUAT,
    trigger: float = 0.0,
) -> TensorGroup:
    """Build a present (valid) ControllerInput TensorGroup with the given grip/aim pose / trigger.

    The grip pose drives roll; the aim pose (pointer ray) drives pitch.
    """
    tg = TensorGroup(ControllerInput())
    tg[ControllerInputIndex.GRIP_POSITION] = np.asarray(grip_pos, dtype=np.float32)
    tg[ControllerInputIndex.GRIP_ORIENTATION] = np.asarray(grip_ori, dtype=np.float32)
    tg[ControllerInputIndex.GRIP_IS_VALID] = True
    tg[ControllerInputIndex.AIM_ORIENTATION] = np.asarray(aim_ori, dtype=np.float32)
    tg[ControllerInputIndex.AIM_IS_VALID] = True
    tg[ControllerInputIndex.TRIGGER_VALUE] = float(trigger)
    return tg


def _make_home_transform(translation) -> np.ndarray:
    """Build a (4, 4) ``base_T_ee`` home transform with identity rotation and the given origin."""
    m = np.eye(4, dtype=np.float64)
    m[:3, 3] = np.asarray(translation, dtype=np.float64)
    return m


def _quat_xyzw(axis, angle_rad: float) -> np.ndarray:
    """Build an [x, y, z, w] quaternion for a rotation of ``angle_rad`` about a unit ``axis``."""
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    half = 0.5 * angle_rad
    xyz = axis * math.sin(half)
    return np.array([xyz[0], xyz[1], xyz[2], math.cos(half)], dtype=np.float64)


def _read_pose(outputs) -> np.ndarray:
    """Read the 7D ee_pose output as a numpy array."""
    return np.asarray(np.from_dlpack(outputs["ee_pose"][0]), dtype=np.float64)


# ===========================================================================
# SO101GripperRetargeter
# ===========================================================================


class TestSO101GripperTriggerMath:
    """The pure ``_trigger_to_closedness`` mapping (deadzone + rescale + clamp)."""

    def test_released_is_open(self):
        """A fully released trigger maps to closedness 0 (jaw open)."""
        assert _trigger_to_closedness(0.0) == pytest.approx(0.0)

    def test_full_press_is_closed(self):
        """A fully pressed trigger maps to closedness 1 (jaw closed)."""
        assert _trigger_to_closedness(1.0) == pytest.approx(1.0)

    def test_deadzone_stays_open(self):
        """A trigger within the released-end deadzone stays at closedness 0."""
        assert _trigger_to_closedness(_TRIGGER_DEADZONE) == pytest.approx(0.0)
        assert _trigger_to_closedness(_TRIGGER_DEADZONE - 0.01) == pytest.approx(0.0)

    def test_half_press_is_mid(self):
        """A half-pressed trigger maps to roughly half-closed (monotonic, mid-range)."""
        c = _trigger_to_closedness(0.5)
        assert 0.4 < c < 0.6
        assert _trigger_to_closedness(0.0) < c < _trigger_to_closedness(1.0)

    def test_clamps_out_of_range(self):
        """Trigger values outside [0, 1] clamp to the closedness endpoints."""
        assert _trigger_to_closedness(-0.5) == pytest.approx(0.0)
        assert _trigger_to_closedness(1.5) == pytest.approx(1.0)


class TestSO101GripperRetargeter:
    """End-to-end ``compute`` behavior of the analog gripper retargeter."""

    def test_output_spec_is_single_scalar(self):
        """Outputs exactly one scalar under the gripper command key."""
        r = SO101GripperRetargeter(name="gripper")
        spec = r.output_spec()
        assert list(spec) == [GRIPPER_COMMAND_KEY]

    def test_full_press_closes(self):
        """A fully pressed trigger drives the jaw closed (c == 1)."""
        r = SO101GripperRetargeter(name="gripper")
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(trigger=1.0)
        r.compute(inputs, outputs, _make_context())
        assert float(outputs[GRIPPER_COMMAND_KEY][0]) == pytest.approx(1.0)

    def test_release_opens(self):
        """A released trigger drives the jaw open (c == 0)."""
        r = SO101GripperRetargeter(name="gripper")
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(trigger=0.0)
        r.compute(inputs, outputs, _make_context())
        assert float(outputs[GRIPPER_COMMAND_KEY][0]) == pytest.approx(0.0)

    def test_dropped_frame_holds_last(self):
        """An absent controller frame holds the last commanded closedness."""
        r = SO101GripperRetargeter(name="gripper")
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(trigger=1.0)
        r.compute(inputs, outputs, _make_context())

        # Next frame: controller absent -> hold the previous closedness (1.0).
        inputs2, outputs2 = _build_io(r)
        r.compute(inputs2, outputs2, _make_context())
        assert float(outputs2[GRIPPER_COMMAND_KEY][0]) == pytest.approx(1.0)

    def test_reset_reopens(self):
        """A reset returns the jaw to fully open even after a closed frame."""
        r = SO101GripperRetargeter(name="gripper")
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(trigger=1.0)
        r.compute(inputs, outputs, _make_context())

        # Reset with an absent controller -> the held value is forced back to open.
        inputs2, outputs2 = _build_io(r)
        r.compute(inputs2, outputs2, _make_context(reset=True))
        assert float(outputs2[GRIPPER_COMMAND_KEY][0]) == pytest.approx(0.0)


# ===========================================================================
# SO101RollRetargeter
# ===========================================================================


class TestSwingTwistAngle:
    """The pure swing-twist decomposition used by the roll retargeter."""

    def test_identity_is_zero(self):
        """The identity quaternion has zero twist about any axis."""
        assert _swing_twist_angle(
            np.array([0.0, 0.0, 0.0, 1.0]), _APPROACH_AXIS
        ) == pytest.approx(0.0)

    @pytest.mark.parametrize("phi", [0.3, 1.0, -0.7, 2.5, -2.5])
    def test_pure_roll_about_z(self, phi):
        """A pure roll of phi about Z recovers phi."""
        q = _quat_xyzw([0.0, 0.0, 1.0], phi)
        assert _swing_twist_angle(q, _APPROACH_AXIS) == pytest.approx(phi, abs=1e-9)

    @pytest.mark.parametrize("axis", [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    def test_pure_swing_is_zero(self, axis):
        """A pure swing (tilt) about X or Y has zero twist about Z."""
        q = _quat_xyzw(axis, 0.9)
        assert _swing_twist_angle(q, _APPROACH_AXIS) == pytest.approx(0.0, abs=1e-9)

    def test_sign(self):
        """Twist sign follows the rotation sign about the axis."""
        assert (
            _swing_twist_angle(_quat_xyzw([0.0, 0.0, 1.0], 0.6), _APPROACH_AXIS) > 0.0
        )
        assert (
            _swing_twist_angle(_quat_xyzw([0.0, 0.0, 1.0], -0.6), _APPROACH_AXIS) < 0.0
        )

    def test_near_180_swing_guard(self):
        """A ~180-degree swing about X (no twist component) hits the degeneracy guard."""
        q = _quat_xyzw([1.0, 0.0, 0.0], math.pi)
        assert _swing_twist_angle(q, _APPROACH_AXIS) == pytest.approx(0.0, abs=1e-9)

    def test_scipy_cross_check_orthogonal_swing(self):
        """Cross-check the twist against scipy for a roll composed with an orthogonal swing."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        phi = 0.8
        r_swing = Rotation.from_rotvec([0.5, 0.0, 0.0])
        r_twist = Rotation.from_rotvec([0.0, 0.0, phi])
        q = (r_twist * r_swing).as_quat()  # scipy returns [x, y, z, w]
        assert _swing_twist_angle(q, _APPROACH_AXIS) == pytest.approx(phi, abs=1e-9)

    def test_scipy_cross_check_non_orthogonal_swing(self):
        """Cross-check against scipy for a NON-orthogonal swing (swing axis has a Z component).

        The orthogonal-X-swing case passes under either twist convention, so it does not pin the
        decomposition. A swing about an axis with a Z component genuinely exercises the
        swing-twist split: the recovered twist is no longer simply the planted ``phi``.
        """
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        phi = 0.8
        swing_axis = np.array([1.0, 0.0, 0.4])
        swing_axis = swing_axis / np.linalg.norm(swing_axis)
        r_swing = Rotation.from_rotvec(0.6 * swing_axis)
        r_twist = Rotation.from_rotvec([0.0, 0.0, phi])
        q = (r_twist * r_swing).as_quat()

        # Independent quaternion-projection twist about Z (oracle).
        qn = np.asarray(q, dtype=np.float64)
        if qn[3] < 0.0:
            qn = -qn
        twist = np.array([0.0, 0.0, qn[2], qn[3]])
        twist /= np.linalg.norm(twist)
        expected = 2.0 * math.atan2(twist[2], twist[3])

        assert (
            abs(expected - phi) > 0.05
        )  # the non-orthogonal swing genuinely perturbs the twist
        assert _swing_twist_angle(q, _APPROACH_AXIS) == pytest.approx(
            expected, abs=1e-9
        )


class TestRollTwistMath:
    """The pure relative-twist helper: twist of ``ref^-1 . cur`` about the controller local axis."""

    def test_pure_local_roll_recovered(self):
        """A pure roll about the local axis since the reference is recovered 1:1."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        R0 = Rotation.from_euler(
            "y", 90, degrees=True
        )  # tilted grasp (approach horizontal)
        phi = 0.5
        cur = (R0 * Rotation.from_rotvec([0.0, 0.0, phi])).as_quat()
        assert _roll_twist(R0.as_quat(), cur, _APPROACH_AXIS) == pytest.approx(
            phi, abs=1e-9
        )

    @pytest.mark.parametrize("axis", [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    def test_off_axis_rotation_rejected(self, axis):
        """A rotation about a local axis perpendicular to the roll axis yields ~zero twist."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        R0 = Rotation.from_euler("y", 90, degrees=True)
        cur = (R0 * Rotation.from_rotvec(np.array(axis) * 0.5)).as_quat()
        assert _roll_twist(R0.as_quat(), cur, _APPROACH_AXIS) == pytest.approx(
            0.0, abs=1e-9
        )

    def test_identity_reference_matches_swing_twist(self):
        """With an identity reference the relative twist equals the absolute swing-twist."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        cur = Rotation.from_rotvec([0.2, -0.1, 0.4]).as_quat()
        ident = np.array([0.0, 0.0, 0.0, 1.0])
        assert _roll_twist(ident, cur, _APPROACH_AXIS) == pytest.approx(
            _swing_twist_angle(cur, _APPROACH_AXIS), abs=1e-12
        )


class TestSO101RollRetargeter:
    """End-to-end ``compute`` behavior of the wrist-roll retargeter (engage-relative)."""

    @staticmethod
    def _roll(r, grip_ori, **ctx):
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(
            grip_ori=np.asarray(grip_ori, dtype=np.float32)
        )
        r.compute(inputs, outputs, _make_context(**ctx))
        return float(outputs[ROLL_COMMAND_KEY][0])

    def test_output_spec_has_roll_command_key(self):
        """Output spec contains the roll command key (among other channels)."""
        r = SO101RollRetargeter(name="roll")
        assert ROLL_COMMAND_KEY in r.output_spec()

    def test_engage_emits_offset(self):
        """The first RUNNING frame latches the reference orientation and emits the offset seed."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        r = SO101RollRetargeter(name="roll")
        out = self._roll(r, Rotation.from_euler("y", 90, degrees=True).as_quat())
        assert out == pytest.approx(_WRIST_ROLL_OFFSET_RAD, abs=1e-6)

    @pytest.mark.parametrize("phi", [0.4, -1.1, 2.0])
    def test_relative_roll_about_local_z(self, phi):
        """A roll of phi about the controller local Z since engage emits roll == offset + phi."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        r = SO101RollRetargeter(name="roll")
        R0 = Rotation.from_euler(
            "xy", [20, 35], degrees=True
        )  # arbitrary engage orientation
        self._roll(r, R0.as_quat())  # engage
        out = self._roll(r, (R0 * Rotation.from_rotvec([0.0, 0.0, phi])).as_quat())
        assert out == pytest.approx(_WRIST_ROLL_OFFSET_RAD + phi, abs=1e-6)

    def test_off_axis_rotations_do_not_leak(self):
        """Pitch/yaw about local axes perpendicular to the roll axis do not move the roll output.

        This is the regression for the cross-coupling bug: with the old absolute twist about a
        fixed world axis, a hand pitch or yaw at a non-vertical grasp leaked fully into wrist_roll.
        """
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        r = SO101RollRetargeter(name="roll")
        R0 = Rotation.from_euler(
            "y", 90, degrees=True
        )  # approach horizontal: worst case for fixed-Z
        self._roll(r, R0.as_quat())  # engage
        # Rotations about local X and local Y (perpendicular to the local-Z roll axis) -> stay at
        # the engage seed (offset).
        assert self._roll(
            r, (R0 * Rotation.from_rotvec([0.5, 0.0, 0.0])).as_quat()
        ) == pytest.approx(_WRIST_ROLL_OFFSET_RAD, abs=1e-6)
        assert self._roll(
            r, (R0 * Rotation.from_rotvec([0.0, 0.5, 0.0])).as_quat()
        ) == pytest.approx(_WRIST_ROLL_OFFSET_RAD, abs=1e-6)
        # A roll about local Z still maps 1:1 on top of the offset.
        assert self._roll(
            r, (R0 * Rotation.from_rotvec([0.0, 0.0, 0.5])).as_quat()
        ) == pytest.approx(_WRIST_ROLL_OFFSET_RAD + 0.5, abs=1e-6)

    def test_reengage_resumes_running_roll(self):
        """A re-clutch resumes from the last commanded roll (no snap), then accumulates."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        r = SO101RollRetargeter(name="roll")
        self._roll(r, Rotation.identity().as_quat())  # engage at identity
        phi1 = 0.6
        base = _WRIST_ROLL_OFFSET_RAD
        assert self._roll(
            r, Rotation.from_rotvec([0.0, 0.0, phi1]).as_quat()
        ) == pytest.approx(base + phi1, abs=1e-6)

        # Disengage (STOPPED) -> hold, re-arm reference.
        assert self._roll(
            r, Rotation.identity().as_quat(), state=ExecutionState.STOPPED
        ) == pytest.approx(base + phi1, abs=1e-6)
        assert r._ref_quat is None

        # Re-engage at a NEW orientation -> resume from base + phi1 (no jump), then a further
        # local-Z roll of phi2 accumulates on top.
        R1 = Rotation.from_euler("z", 80, degrees=True)
        assert self._roll(r, R1.as_quat()) == pytest.approx(base + phi1, abs=1e-6)
        phi2 = -0.3
        assert self._roll(
            r, (R1 * Rotation.from_rotvec([0.0, 0.0, phi2])).as_quat()
        ) == pytest.approx(base + phi1 + phi2, abs=1e-6)

    def test_reset_returns_to_offset(self):
        """A reset re-zeros the running roll back to the offset seed."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        r = SO101RollRetargeter(name="roll")
        self._roll(r, Rotation.identity().as_quat())  # engage
        self._roll(r, Rotation.from_rotvec([0.0, 0.0, 0.9]).as_quat())  # roll away
        out = self._roll(r, Rotation.identity().as_quat(), reset=True)
        assert out == pytest.approx(_WRIST_ROLL_OFFSET_RAD, abs=1e-6)

    def test_not_running_holds_without_latching(self):
        """While not RUNNING the roll holds the last value and does not latch a reference."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        r = SO101RollRetargeter(name="roll")
        out = self._roll(
            r,
            Rotation.from_rotvec([0.0, 0.0, 0.7]).as_quat(),
            state=ExecutionState.STOPPED,
        )
        assert out == pytest.approx(
            _WRIST_ROLL_OFFSET_RAD, abs=1e-6
        )  # offset, never engaged
        assert r._ref_quat is None

    def test_dropped_frame_holds_last(self):
        """An absent controller frame holds the last commanded roll."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        r = SO101RollRetargeter(name="roll")
        self._roll(r, Rotation.identity().as_quat())  # engage
        self._roll(
            r, Rotation.from_rotvec([0.0, 0.0, 0.7]).as_quat()
        )  # roll to offset + 0.7

        inputs2, outputs2 = _build_io(r)  # controller absent
        r.compute(inputs2, outputs2, _make_context())
        assert float(outputs2[ROLL_COMMAND_KEY][0]) == pytest.approx(
            _WRIST_ROLL_OFFSET_RAD + 0.7, abs=1e-6
        )

    def test_roll_alias_points_at_wrist_retargeter(self):
        """The legacy SO101RollRetargeter name still resolves (back-compat alias)."""
        from isaacteleop.retargeters import SO101RollRetargeter as Legacy
        from isaacteleop.retargeters import SO101WristRetargeter

        assert Legacy is SO101WristRetargeter


# ===========================================================================
# SO101WristRetargeter (pitch channel)
# ===========================================================================


class TestApproachElevationMath:
    """The pure approach-axis elevation helper used by the wrist retargeter's pitch channel."""

    def test_horizontal_is_zero(self):
        """An orientation that rotates the approach axis into the horizontal plane gives 0."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        # Rotate the approach axis (+Z) to horizontal via +90deg about Y -> [1, 0, 0].
        q = Rotation.from_euler("y", 90, degrees=True).as_quat()
        assert _approach_elevation(q) == pytest.approx(0.0, abs=1e-9)

    def test_identity_points_along_approach_axis(self):
        """At identity the approach axis is _PITCH_APPROACH_AXIS, so elevation is its own."""
        expected = math.atan2(
            _PITCH_APPROACH_AXIS[2],
            math.hypot(_PITCH_APPROACH_AXIS[0], _PITCH_APPROACH_AXIS[1]),
        )
        assert _approach_elevation(_ID_QUAT) == pytest.approx(expected, abs=1e-9)

    @pytest.mark.parametrize(
        "euler", [(0, 30, 0), (0, -25, 0), (45, 0, 0), (20, 35, 10), (0, 90, 0)]
    )
    def test_matches_scipy_for_arbitrary_orientation(self, euler):
        """Cross-check the helper's quaternion math against scipy for arbitrary orientations.

        Rotating the approach axis by the orientation and taking atan2(z, ||xy||) is the oracle;
        the helper must match it (guards the quaternion sandwich/convention, not a planted angle).
        """
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        R = Rotation.from_euler("xyz", euler, degrees=True)
        axis = R.apply(_PITCH_APPROACH_AXIS)
        expected = math.atan2(axis[2], math.hypot(axis[0], axis[1]))
        assert _approach_elevation(R.as_quat()) == pytest.approx(expected, abs=1e-9)


class TestSO101WristRetargeterPitch:
    """The wrist retargeter emits an ABSOLUTE pitch channel (no engage latching)."""

    @staticmethod
    def _pitch(r, aim_ori, **ctx):
        # Pitch is driven by the AIM pose (pointer ray), not the grip pose.
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(
            aim_ori=np.asarray(aim_ori, dtype=np.float32)
        )
        r.compute(inputs, outputs, _make_context(**ctx))
        return float(outputs[PITCH_COMMAND_KEY][0])

    def test_output_spec_has_pitch_and_roll(self):
        """The wrist retargeter exposes both the roll and pitch command channels."""
        from isaacteleop.retargeters.SO101.wrist_retargeter import ROLL_COMMAND_KEY

        r = SO101WristRetargeter(name="wrist")
        assert set(r.output_spec()) == {ROLL_COMMAND_KEY, PITCH_COMMAND_KEY}

    def test_pitch_is_absolute_not_engage_relative(self):
        """The same aim pose yields the same pitch regardless of when teleop engaged."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        pose = Rotation.from_euler("y", 30, degrees=True).as_quat()
        # Two frames suffice: pitch has no accumulated/engage state, so this test would catch
        # a future regression that added engage-relative pitch state.
        r1 = SO101WristRetargeter(name="wrist")
        first = self._pitch(r1, pose)  # engage frame
        r2 = SO101WristRetargeter(name="wrist")
        self._pitch(
            r2, Rotation.from_euler("y", -50, degrees=True).as_quat()
        )  # different engage
        second = self._pitch(r2, pose)
        assert first == pytest.approx(second, abs=1e-6)

    def test_pitch_dropped_frame_holds_last(self):
        """An absent controller frame holds the last commanded pitch."""
        Rotation = pytest.importorskip("scipy.spatial.transform").Rotation
        r = SO101WristRetargeter(name="wrist")
        self._pitch(r, Rotation.from_euler("y", 20, degrees=True).as_quat())
        inputs2, outputs2 = _build_io(r)  # controller absent
        r.compute(inputs2, outputs2, _make_context())
        held = float(outputs2[PITCH_COMMAND_KEY][0])
        again = self._pitch(r, Rotation.from_euler("y", 20, degrees=True).as_quat())
        assert held == pytest.approx(again, abs=1e-6)


# ===========================================================================
# SO101ClutchRetargeter
# ===========================================================================


class TestRebasedPositionMath:
    """The pure clutch rebasing math (origin + scale). Controller poses arrive already in the
    robot base frame (the Lab device rebases them via ``target_frame_prim_path``), so no
    world->base rotation is applied here."""

    HOME = np.array(_CLUTCH_HOME_EE_POS, dtype=np.float64)
    ORIGIN = np.array([0.31, -0.12, 0.44], dtype=np.float64)

    def test_first_frame_is_home(self):
        """With ``p_ctrl == origin`` (the latching frame), the rebased position is exactly home."""
        out = _rebased_position(self.ORIGIN.copy(), self.ORIGIN, self.HOME, 1.0)
        np.testing.assert_allclose(out, self.HOME, atol=1e-9)

    def test_applies_delta(self):
        """A +delta controller move shifts the EE by +delta from home (scale 1)."""
        delta = np.array([0.05, -0.02, 0.10], dtype=np.float64)
        out = _rebased_position(self.ORIGIN + delta, self.ORIGIN, self.HOME, 1.0)
        np.testing.assert_allclose(out, self.HOME + delta, atol=1e-9)

    def test_honors_scale(self):
        """The translation scale multiplies the controller delta before adding it to home."""
        delta = np.array([0.05, -0.02, 0.10], dtype=np.float64)
        out = _rebased_position(self.ORIGIN + delta, self.ORIGIN, self.HOME, 2.0)
        np.testing.assert_allclose(out, self.HOME + 2.0 * delta, atol=1e-9)


class TestSO101ClutchRetargeter:
    """End-to-end ``compute`` behavior of the clutch EE-pose retargeter."""

    def test_output_spec_is_7d_pose(self):
        """Outputs a single 7D ee_pose (position + quaternion)."""
        r = SO101ClutchRetargeter(name="ee_pose")
        pose_type = r.output_spec()["ee_pose"].types[0]
        assert pose_type.shape == (7,)

    def test_input_spec_is_controller_only(self):
        """The clutch consumes only the controller; no live EE or base transform inputs.

        The world->base rebase happens upstream (the device's ``target_frame_prim_path``) and the
        reset-origin home is the static ``home_base_T_ee`` config, so the clutch needs neither a
        per-frame ``robot_ee_pos`` nor a ``robot_base_pos`` input.
        """
        r = SO101ClutchRetargeter(name="ee_pose")
        assert list(r.input_spec()) == [ControllersSource.RIGHT]
        assert not hasattr(SO101ClutchRetargeter, "ROBOT_EE_POS_INPUT")
        assert not hasattr(SO101ClutchRetargeter, "ROBOT_BASE_POS_INPUT")

    def test_not_running_holds_home_without_latching(self):
        """While not RUNNING the clutch holds the configured home and does not latch an origin."""
        r = SO101ClutchRetargeter(name="ee_pose")
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=(0.5, 0.5, 0.5))
        r.compute(inputs, outputs, _make_context(state=ExecutionState.STOPPED))
        pose = _read_pose(outputs)
        np.testing.assert_allclose(pose[:3], np.array(_CLUTCH_HOME_EE_POS), atol=1e-6)
        assert r._origin is None  # not latched while stopped

    def test_engage_latches_origin_at_home(self):
        """The first RUNNING frame latches the origin so the EE sits exactly at the configured home.

        On the latching frame ``p_ctrl == origin`` so the emitted position equals home (no
        teleport on engage). The grip orientation passes through unchanged.
        """
        r = SO101ClutchRetargeter(name="ee_pose")
        inputs, outputs = _build_io(r)
        grip_ori = _quat_xyzw([0, 0, 1], 0.3).astype(np.float32)
        inputs[ControllersSource.RIGHT] = _make_controller(
            grip_pos=(0.5, -0.3, 0.7), grip_ori=grip_ori
        )
        r.compute(inputs, outputs, _make_context())
        pose = _read_pose(outputs)
        np.testing.assert_allclose(pose[:3], np.array(_CLUTCH_HOME_EE_POS), atol=1e-6)
        np.testing.assert_allclose(pose[3:], grip_ori, atol=1e-6)

    def test_motion_after_engage_applies_delta(self):
        """A controller delta after engage shifts the EE by that delta from home (base frame)."""
        r = SO101ClutchRetargeter(name="ee_pose")
        p0 = np.array([0.5, -0.3, 0.7])
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=p0)
        r.compute(inputs, outputs, _make_context())  # engage frame: latch origin == p0

        delta = np.array([0.05, -0.02, 0.10])
        inputs2, outputs2 = _build_io(r)
        inputs2[ControllersSource.RIGHT] = _make_controller(grip_pos=p0 + delta)
        r.compute(inputs2, outputs2, _make_context())
        pose = _read_pose(outputs2)
        expected = np.array(_CLUTCH_HOME_EE_POS) + delta
        np.testing.assert_allclose(pose[:3], expected, atol=1e-5)

    def test_configured_home_overrides_default(self):
        """A ``home_base_T_ee`` transform sets the engage home from its translation block."""
        home_xyz = (0.30, 0.10, 0.25)
        r = SO101ClutchRetargeter(
            name="ee_pose", home_base_T_ee=_make_home_transform(home_xyz)
        )
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=(0.5, -0.3, 0.7))
        r.compute(inputs, outputs, _make_context())
        np.testing.assert_allclose(
            _read_pose(outputs)[:3], np.array(home_xyz), atol=1e-6
        )

    def test_reengage_resumes_from_last_commanded_pose(self):
        """A mid-task re-clutch resumes from the last commanded pose (no snap), then accumulates.

        The clutch keeps its own running home internally. After a plain Stop, the next Play
        latches the origin to the new controller pose but keeps the home at the last commanded
        pose, so the arm stays put and tracks fresh delta from there.
        """
        r = SO101ClutchRetargeter(name="ee_pose")
        home = np.array(_CLUTCH_HOME_EE_POS)
        p0 = np.array([0.5, -0.3, 0.7])

        # Engage (seeds home from config) and move +d1 -> last commanded is home + d1.
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=p0)
        r.compute(inputs, outputs, _make_context())
        d1 = np.array([0.05, -0.02, 0.10])
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=p0 + d1)
        r.compute(inputs, outputs, _make_context())
        np.testing.assert_allclose(_read_pose(outputs)[:3], home + d1, atol=1e-5)

        # Disengage (STOPPED) -> hold last commanded pose, re-arm the origin.
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=(9.0, 9.0, 9.0))
        r.compute(inputs, outputs, _make_context(state=ExecutionState.STOPPED))
        np.testing.assert_allclose(_read_pose(outputs)[:3], home + d1, atol=1e-5)
        assert r._origin is None

        # Re-engage at a new controller pose -> resume from the running home (home + d1): no jump.
        p1 = np.array([1.0, 1.0, 1.0])
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=p1)
        r.compute(inputs, outputs, _make_context())
        np.testing.assert_allclose(_read_pose(outputs)[:3], home + d1, atol=1e-5)

        # Fresh delta from the re-engage origin accumulates on top of the resumed pose.
        d2 = np.array([0.0, 0.10, -0.03])
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=p1 + d2)
        r.compute(inputs, outputs, _make_context())
        np.testing.assert_allclose(_read_pose(outputs)[:3], home + d1 + d2, atol=1e-5)

    def test_reset_returns_home_to_config(self):
        """An explicit reset returns the running home to the configured home.

        Unlike a plain Stop (which freezes the running home so re-engage resumes), a reset
        re-zeros the clutch to the configured home for a fresh episode.
        """
        r = SO101ClutchRetargeter(name="ee_pose")
        home = np.array(_CLUTCH_HOME_EE_POS)
        p0 = np.array([0.5, -0.3, 0.7])

        # Engage and move so the running home is no longer the configured home.
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=p0)
        r.compute(inputs, outputs, _make_context())
        d1 = np.array([0.05, -0.02, 0.10])
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=p0 + d1)
        r.compute(inputs, outputs, _make_context())

        # Reset (controller steady at p0) -> re-zeros the home to config and re-latches the
        # origin at p0, so the emitted pose is the configured home, not the pre-reset pose.
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=p0)
        r.compute(inputs, outputs, _make_context(reset=True))
        np.testing.assert_allclose(_read_pose(outputs)[:3], home, atol=1e-6)

        # Subsequent motion is measured from the config home (not the pre-reset commanded pose).
        d2 = np.array([0.0, 0.10, -0.03])
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=p0 + d2)
        r.compute(inputs, outputs, _make_context())
        np.testing.assert_allclose(_read_pose(outputs)[:3], home + d2, atol=1e-6)

    def test_dropped_frame_holds_last_pose(self):
        """An absent controller frame holds the last commanded pose."""
        r = SO101ClutchRetargeter(name="ee_pose")
        p0 = np.array([0.5, -0.3, 0.7])
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(grip_pos=p0)
        r.compute(inputs, outputs, _make_context())
        first = _read_pose(outputs)

        inputs2, outputs2 = _build_io(r)  # controller absent
        r.compute(inputs2, outputs2, _make_context())
        np.testing.assert_allclose(_read_pose(outputs2), first, atol=1e-9)
