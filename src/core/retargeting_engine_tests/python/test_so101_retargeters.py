# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Sim-free unit tests for the SO-101 XR teleop retargeters.

Covers the SO-101 retargeters that drive the full-pose SE3 IK stacking pipeline:

* :class:`~isaacteleop.retargeters.SO101GripperRetargeter` -- analog trigger -> jaw closedness.
* :class:`~isaacteleop.retargeters.SO101ClutchRetargeter` -- clutch-rebased absolute EE pose
  (position + calibration-composed grip orientation) for the 5-joint pose IK.

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
)
from isaacteleop.retargeters.SO101.clutch_retargeter import (
    _CLUTCH_HOME_EE_POS,
    _quat_mul,
    _rebased_position,
)
from isaacteleop.retargeters.SO101.gripper_retargeter import (
    GRIPPER_COMMAND_KEY,
    _TRIGGER_DEADZONE,
    _trigger_to_closedness,
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
        teleport on engage). An identity offset is used here so the grip orientation passes
        through unchanged (the default ``Rz(pi)`` offset is covered by
        :meth:`test_calibration_offset_composed_into_orientation`).
        """
        r = SO101ClutchRetargeter(
            name="ee_pose", orientation_offset=np.array([0.0, 0.0, 0.0, 1.0])
        )
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

    def test_calibration_offset_composed_into_orientation(self):
        """The fixed orientation offset right-multiplies (body frame) the grip orientation.

        The default offset is ``Rz(pi)`` (a roll about the shared approach axis), composed as a
        body-frame right multiply (``grip (x) offset``) and renormalized to unit. An explicit
        identity offset passes the grip orientation through unchanged.
        """
        grip = _quat_xyzw([0.0, 1.0, 0.0], 0.4).astype(np.float32)

        # Explicit identity offset: passthrough.
        r = SO101ClutchRetargeter(
            name="ee_pose", orientation_offset=np.array([0.0, 0.0, 0.0, 1.0])
        )
        inputs, outputs = _build_io(r)
        inputs[ControllersSource.RIGHT] = _make_controller(
            grip_pos=(0.5, -0.3, 0.7), grip_ori=grip
        )
        r.compute(inputs, outputs, _make_context())
        np.testing.assert_allclose(_read_pose(outputs)[3:], grip, atol=1e-6)

        # Default offset: emitted == grip (x) Rz(pi) (body-frame right multiply), unit.
        r_def = SO101ClutchRetargeter(name="ee_pose")
        inputs_def, outputs_def = _build_io(r_def)
        inputs_def[ControllersSource.RIGHT] = _make_controller(
            grip_pos=(0.5, -0.3, 0.7), grip_ori=grip
        )
        r_def.compute(inputs_def, outputs_def, _make_context())
        rz_pi = np.array([0.0, 0.0, 1.0, 0.0])  # Rz(pi), xyzw
        expected_def = _quat_mul(grip.astype(np.float64), rz_pi)
        expected_def = expected_def / np.linalg.norm(expected_def)
        np.testing.assert_allclose(_read_pose(outputs_def)[3:], expected_def, atol=1e-6)

        # Non-identity offset: emitted == grip (x) offset (right multiply), renormalized to unit.
        offset = _quat_xyzw([0.0, 0.0, 1.0], 0.9)
        r2 = SO101ClutchRetargeter(name="ee_pose", orientation_offset=offset)
        inputs2, outputs2 = _build_io(r2)
        inputs2[ControllersSource.RIGHT] = _make_controller(
            grip_pos=(0.5, -0.3, 0.7), grip_ori=grip
        )
        r2.compute(inputs2, outputs2, _make_context())
        emitted = _read_pose(outputs2)[3:]
        expected = _quat_mul(grip.astype(np.float64), offset)
        expected = expected / np.linalg.norm(expected)
        np.testing.assert_allclose(emitted, expected, atol=1e-6)
        assert np.linalg.norm(emitted) == pytest.approx(1.0, abs=1e-6)
