# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Sim-free unit tests for the SO-101 XR teleop retargeters.

Covers the SO-101 retargeters that drive the full-pose SE3 IK stacking pipeline:

* :class:`~isaacteleop.retargeters.SO101GripperRetargeter` -- analog trigger -> jaw closedness.
* :class:`~isaacteleop.retargeters.SO101ClutchRetargeter` -- the engage-relative full-pose clutch,
  re-latching both home position and orientation on every engage with a base-frame left-composed
  orientation delta.

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
    OutputCombiner,
    TensorGroup,
    ValueInput,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import GraphTime
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    OptionalTensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
    TransformMatrix,
)
from isaacteleop.retargeters import (
    SO101ClutchRetargeter,
    SO101GripperRetargeter,
)
from isaacteleop.retargeters.SO101.clutch_retargeter import (
    _mat_to_quat_xyzw,
    _normalize_quat,
    _quat_inv,
    _quat_mul,
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
    squeeze: float = 0.0,
    grip_is_valid: bool = True,
) -> TensorGroup:
    """Build a present ControllerInput TensorGroup with the given grip/aim pose / trigger.

    The grip pose drives roll; the aim pose (pointer ray) drives pitch. ``grip_is_valid`` sets the
    grip pose validity flag (OpenXR location-flag derived); pass ``False`` to model a present
    controller whose grip pose is not yet localizable.

    ``squeeze`` is the grip/squeeze trigger that drives
    :class:`SO101ClutchRetargeter`'s engage signal.

    ALL 14 elements are written, matching what the real ``ControllersSource._update_group`` does.
    Two distinct things require it: reading an unset element raises ``ValueError``
    (``interface/tensor.py:83-84``), and passing this group through a ``ValueInput`` in a graph
    deep-copies every slot -- so a partially-populated group fails on a slot nothing even reads.
    """
    tg = TensorGroup(ControllerInput())
    tg[ControllerInputIndex.GRIP_POSITION] = np.asarray(grip_pos, dtype=np.float32)
    tg[ControllerInputIndex.GRIP_ORIENTATION] = np.asarray(grip_ori, dtype=np.float32)
    tg[ControllerInputIndex.GRIP_IS_VALID] = grip_is_valid
    tg[ControllerInputIndex.AIM_POSITION] = np.zeros(3, dtype=np.float32)
    tg[ControllerInputIndex.AIM_ORIENTATION] = np.asarray(aim_ori, dtype=np.float32)
    tg[ControllerInputIndex.AIM_IS_VALID] = True
    tg[ControllerInputIndex.PRIMARY_CLICK] = 0.0
    tg[ControllerInputIndex.SECONDARY_CLICK] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_X] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_Y] = 0.0
    tg[ControllerInputIndex.THUMBSTICK_CLICK] = 0.0
    tg[ControllerInputIndex.MENU_CLICK] = 0.0
    tg[ControllerInputIndex.TRIGGER_VALUE] = float(trigger)
    tg[ControllerInputIndex.SQUEEZE_VALUE] = float(squeeze)
    return tg


def _make_home_transform(translation, rotation_3x3=None) -> np.ndarray:
    """Build a (4, 4) ``base_T_ee`` home transform from a translation and optional rotation.

    The rotation defaults to identity. :class:`SO101ClutchRetargeter` reads both blocks.
    """
    m = np.eye(4, dtype=np.float64)
    if rotation_3x3 is not None:
        m[:3, :3] = np.asarray(rotation_3x3, dtype=np.float64)
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
#
# The clutch re-latches BOTH home position and orientation on every engage, and composes the
# orientation delta on the LEFT (base frame). A right-composed delta, or a fixed appended
# orientation offset, is a different convention that breaks the no-teleport invariant.
#
# ``engage()``/``rebase()`` do not exist here -- engagement is a squeeze rising edge observed
# across ``compute()`` frames -- so the invariants below are expressed as frame sequences. A
# rising-edge frame both latches AND emits, so a test whose engage and rebase poses are identical
# needs one frame while a test that moves the controller needs two.


def _quat_to_matrix(q) -> np.ndarray:
    """Convert an [x, y, z, w] quaternion to a 3x3 rotation matrix."""
    x, y, z, w = _normalize_quat(np.asarray(q, dtype=np.float64))
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _rot_dist(a, b) -> float:
    """Frobenius distance between two rotations given as [x, y, z, w] quaternions.

    Deliberately NOT a geodesic ``arccos`` angle: ``arccos((tr - 1) / 2)`` has a ``sqrt(eps)``
    conditioning floor near identity and reports ~5.2e-08 rad for a pair this metric resolves at
    ~4.9e-15, which makes tight tolerances unachievable and reads as a code fault. Frobenius is
    also sign-agnostic by construction (``q`` and ``-q`` are the same rotation).
    """
    return float(np.linalg.norm(_quat_to_matrix(a) - _quat_to_matrix(b)))


def _make_measured(translation) -> TensorGroup:
    """Build a ``base_T_ee`` TransformMatrix group for the measured-EE-pose input."""
    tg = TensorGroup(TransformMatrix())
    tg[0] = _make_home_transform(translation).astype(np.float32)
    return tg


class _Driver:
    """Drives a :class:`SO101ClutchRetargeter` one frame at a time.

    Named for what it does rather than for the class under test: this file also exercises the
    SO-101 gripper retargeter, so a bare ``_Clutch`` would read as the only subject here.
    """

    def __init__(self, home_base_T_ee=None, **kwargs):  # noqa: N803
        if home_base_T_ee is None:
            home_base_T_ee = _make_home_transform((0.0, 0.0, 0.0))
        self.r = SO101ClutchRetargeter("clutch", home_base_T_ee, **kwargs)
        self.inputs, self.outputs = _build_io(self.r)

    def frame(
        self,
        grip_pos=(0.0, 0.0, 0.0),
        grip_ori=_ID_QUAT,
        *,
        squeeze: float = 1.0,
        grip_is_valid: bool = True,
        present: bool = True,
        measured=None,
        state: ExecutionState = ExecutionState.RUNNING,
        reset: bool = False,
    ) -> np.ndarray:
        """Drive one frame and return the emitted 7D pose."""
        key = ControllersSource.RIGHT
        if present:
            self.inputs[key] = _make_controller(
                grip_pos=grip_pos,
                grip_ori=grip_ori,
                squeeze=squeeze,
                grip_is_valid=grip_is_valid,
            )
        else:
            self.inputs[key] = OptionalTensorGroup(ControllerInput())
        self.inputs[SO101ClutchRetargeter.MEASURED_BASE_T_EE_INPUT] = (
            _make_measured(measured)
            if measured is not None
            else OptionalTensorGroup(TransformMatrix())
        )
        self.r.compute(
            self.inputs, self.outputs, _make_context(reset=reset, state=state)
        )
        return _read_pose(self.outputs)

    def engage(self, grip_pos=(0.0, 0.0, 0.0), grip_ori=_ID_QUAT, **kw) -> np.ndarray:
        """Release then re-squeeze, so the next frame is a rising edge that latches."""
        self.frame(grip_pos, grip_ori, squeeze=0.0)
        return self.frame(grip_pos, grip_ori, squeeze=1.0, **kw)


class TestEngageRelativeClutchQuaternionHelpers:
    """The inlined quaternion helpers, pinned against independent references.

    The branch-on-trace matrix->quaternion conversion is the one piece of this retargeter that is
    not eyeball-verifiable, so it is checked over random SO(3) with all four Shepperd branches
    covered rather than on a handful of axis rotations.
    """

    def test_mat_to_quat_round_trips_over_random_so3(self):
        """matrix -> quat -> matrix reproduces the input over uniformly random rotations."""
        rng = np.random.default_rng(20260727)
        branches = {"trace": 0, "xx": 0, "yy": 0, "zz": 0}
        worst = 0.0
        for _ in range(2000):
            # QR of a Gaussian matrix is uniform on O(3) only after the sign fix below; without
            # it the sample is badly skewed and two Shepperd branches go almost unvisited.
            q, upper = np.linalg.qr(rng.standard_normal((3, 3)))
            q = q @ np.diag(np.sign(np.diag(upper)))
            if np.linalg.det(q) < 0:
                q[:, 0] *= -1
            if np.trace(q) > 0:
                branches["trace"] += 1
            elif q[0, 0] > q[1, 1] and q[0, 0] > q[2, 2]:
                branches["xx"] += 1
            elif q[1, 1] > q[2, 2]:
                branches["yy"] += 1
            else:
                branches["zz"] += 1
            worst = max(
                worst, float(np.linalg.norm(_quat_to_matrix(_mat_to_quat_xyzw(q)) - q))
            )
        assert worst < 1e-12
        # All four branches must actually be exercised, or this proves much less than it looks.
        assert all(count > 100 for count in branches.values()), branches

    def test_mat_to_quat_handles_180_degree_rotations(self):
        """The trace <= 0 branches: 180 degrees about each principal axis."""
        for axis in np.eye(3):
            expected = _quat_to_matrix(_quat_xyzw(axis, math.pi))
            assert (
                _rot_dist(_mat_to_quat_xyzw(expected), _quat_xyzw(axis, math.pi))
                < 1e-12
            )

    def test_mat_to_quat_output_is_normalized(self):
        """Unlike the engine-private original, this copy normalizes -- downstream assumes unit."""
        m = _quat_to_matrix(_quat_xyzw([1.0, 2.0, 3.0], 1.1))
        assert abs(float(np.linalg.norm(_mat_to_quat_xyzw(m))) - 1.0) < 1e-12

    def test_quat_inv_inverts_even_a_non_unit_quaternion(self):
        """``_quat_inv`` normalizes before conjugating, so non-unit input still inverts."""
        q = np.array([0.3, -0.4, 0.5, 0.7]) * 7.0
        assert _rot_dist(_quat_mul(q, _quat_inv(q)), _ID_QUAT) < 1e-12

    def test_quat_mul_matches_matrix_composition(self):
        """``_quat_mul(a, b)`` composes as ``R(a) @ R(b)`` -- operand order is load-bearing."""
        a = _quat_xyzw([0.0, 0.0, 1.0], math.pi / 2)
        b = _quat_xyzw([1.0, 0.0, 0.0], math.pi / 2)
        expected = _quat_to_matrix(a) @ _quat_to_matrix(b)
        assert (
            float(np.linalg.norm(_quat_to_matrix(_quat_mul(a, b)) - expected)) < 1e-12
        )


class TestEngageRelativeClutchSeeding:
    """The constructor latches home from the supplied startup EE pose -- both blocks."""

    def test_engage_frame_returns_seeded_home_position(self):
        """Engaging at any controller pose returns exactly the seeded home -- no teleport."""
        c = _Driver(_make_home_transform((0.1, 0.2, 0.3)))
        np.testing.assert_allclose(
            c.engage((5.0, -3.0, 2.0))[:3], [0.1, 0.2, 0.3], atol=1e-6
        )

    def test_engage_frame_returns_seeded_home_orientation(self):
        """Same no-teleport guarantee for orientation, whatever the controller orientation."""
        home_rot = _quat_to_matrix(_quat_xyzw([0.0, 1.0, 0.0], math.pi / 3))
        c = _Driver(_make_home_transform((0.0, 0.0, 0.0), home_rot))
        grip = _quat_xyzw([1.0, 0.0, 0.0], math.pi / 5)
        assert (
            _rot_dist(c.engage((0.0, 0.0, 0.0), grip)[3:7], _mat_to_quat_xyzw(home_rot))
            < 1e-6
        )

    def test_home_transform_rotation_block_is_used(self):
        """The rotation block is NOT discarded: it seeds the home orientation."""
        home_rot = _quat_to_matrix(_quat_xyzw([0.0, 0.0, 1.0], math.pi / 2))
        c = _Driver(_make_home_transform((0.0, 0.0, 0.0), home_rot))
        assert _rot_dist(c.frame(squeeze=0.0)[3:7], _mat_to_quat_xyzw(home_rot)) < 1e-6


class TestEngageRelativeClutchPosition:
    """Controller -> EE translation is measured from the engage origin, scaled."""

    def test_position_delta_is_one_to_one(self):
        c = _Driver(_make_home_transform((1.0, 1.0, 1.0)))
        c.engage((0.0, 0.0, 0.0))
        pose = c.frame((0.3, -0.2, 0.0))
        np.testing.assert_allclose(pose[:3], [1.3, 0.8, 1.0], atol=1e-6)

    def test_position_is_relative_to_origin_not_absolute(self):
        """A nonzero engage origin does not leak into the output -- only the change from it."""
        c = _Driver()
        c.engage((10.0, 10.0, 10.0))
        np.testing.assert_allclose(
            c.frame((10.5, 10.0, 10.0))[:3], [0.5, 0.0, 0.0], atol=1e-6
        )


class TestEngageRelativeClutchOrientation:
    """Base-frame (left-composed) orientation delta."""

    def test_orientation_delta_is_base_frame_left_composed(self):
        """R_out = Rz(90) @ Rx(90), NOT the body-frame Rx(90) @ Rz(90) a right-composition gives."""
        home_rot = _quat_to_matrix(_quat_xyzw([1.0, 0.0, 0.0], math.pi / 2))
        c = _Driver(_make_home_transform((0.0, 0.0, 0.0), home_rot))
        c.engage()
        ctrl = _quat_xyzw([0.0, 0.0, 1.0], math.pi / 2)
        out = c.frame((0.0, 0.0, 0.0), ctrl)[3:7]
        expected = _quat_to_matrix(ctrl) @ home_rot
        assert float(np.linalg.norm(_quat_to_matrix(out) - expected)) < 1e-6
        # And it is NOT the right-composed alternative, which differs by O(1).
        assert (
            float(
                np.linalg.norm(_quat_to_matrix(out) - home_rot @ _quat_to_matrix(ctrl))
            )
            > 1.0
        )

    def test_orientation_is_relative_to_origin_orientation(self):
        """A nonzero controller origin orientation cancels on the engage frame."""
        c = _Driver()
        origin = _quat_xyzw([0.0, 0.0, 1.0], math.pi / 4)
        assert _rot_dist(c.engage((0.0, 0.0, 0.0), origin)[3:7], _ID_QUAT) < 1e-6

    def test_orientation_delta_is_always_one_to_one_regardless_of_scale(self):
        """``position_scale`` applies to translation only."""
        c = _Driver(position_scale=0.25)
        c.engage()
        ctrl = _quat_xyzw([0.0, 1.0, 0.0], math.pi / 3)
        assert _rot_dist(c.frame((0.0, 0.0, 0.0), ctrl)[3:7], ctrl) < 1e-6


class TestEngageRelativeClutchReclutch:
    """A fresh engage resumes from the LAST COMMANDED pose."""

    def test_reclutch_resumes_from_last_commanded_position(self):
        c = _Driver()
        c.engage((0.0, 0.0, 0.0))
        c.frame((1.0, 0.0, 0.0))
        # Re-engage with the controller somewhere else entirely: no jump to its absolute position.
        np.testing.assert_allclose(
            c.engage((5.0, 5.0, 5.0))[:3], [1.0, 0.0, 0.0], atol=1e-6
        )
        np.testing.assert_allclose(
            c.frame((6.0, 5.0, 5.0))[:3], [2.0, 0.0, 0.0], atol=1e-6
        )

    def test_reclutch_resumes_from_last_commanded_orientation(self):
        c = _Driver()
        c.engage()
        ctrl = _quat_xyzw([0.0, 0.0, 1.0], math.pi / 2)
        c.frame((0.0, 0.0, 0.0), ctrl)
        reengage = _quat_xyzw([1.0, 0.0, 0.0], math.pi / 3)
        out = c.engage((0.0, 0.0, 0.0), reengage)[3:7]
        assert _rot_dist(out, ctrl) < 1e-6

    def test_disengaged_gap_does_not_change_commanded_pose(self):
        """Only engaged frames advance the commanded pose; disengaged frames hold it."""
        c = _Driver()
        c.engage()
        pose_a = c.frame((0.4, 0.1, -0.2)).copy()
        for _ in range(5):
            c.frame((7.0, 7.0, 7.0), squeeze=0.0)
        pose_b = c.engage((9.0, 9.0, 9.0))
        np.testing.assert_allclose(pose_a[:3], pose_b[:3], atol=1e-6)
        assert _rot_dist(pose_a[3:7], pose_b[3:7]) < 1e-6


class TestEngageRelativeClutchEngageSignal:
    """``engaged == RUNNING and squeeze > squeeze_threshold``, latched on the rising edge."""

    def test_squeeze_below_threshold_does_not_engage(self):
        c = _Driver(squeeze_threshold=0.5)
        c.frame((1.0, 0.0, 0.0), squeeze=0.5)  # strictly greater, so 0.5 is NOT engaged
        assert not c.r.is_engaged
        np.testing.assert_allclose(
            c.frame((1.0, 0.0, 0.0), squeeze=0.51)[:3], [0.0, 0.0, 0.0], atol=1e-6
        )
        assert c.r.is_engaged

    @pytest.mark.parametrize(
        "state",
        [ExecutionState.STOPPED, ExecutionState.PAUSED, ExecutionState.UNKNOWN],
    )
    def test_non_running_state_blocks_engagement(self, state):
        """The RUNNING conjunct is a real readiness interlock, not a vacuous term."""
        c = _Driver()
        c.frame((1.0, 0.0, 0.0), squeeze=1.0, state=state)
        assert not c.r.is_engaged
        np.testing.assert_allclose(
            _read_pose(c.outputs)[:3], [0.0, 0.0, 0.0], atol=1e-6
        )

    def test_is_engaged_rising_edge_is_the_latch_frame(self):
        """The loop derives the engage edge from ``is_engaged``; it must equal the latch."""
        c = _Driver()
        assert not c.r.is_engaged  # False before the first compute
        c.frame((1.0, 0.0, 0.0), squeeze=1.0)
        assert c.r.is_engaged
        c.frame((2.0, 0.0, 0.0), squeeze=0.0)
        assert not c.r.is_engaged

    def test_squeeze_held_across_a_stop_relatches_on_resume(self):
        """Leaving RUNNING disarms, so returning with squeeze held is a fresh rising edge."""
        c = _Driver()
        c.frame((0.0, 0.0, 0.0), squeeze=1.0)
        c.frame((1.0, 0.0, 0.0), squeeze=1.0)
        c.frame((5.0, 0.0, 0.0), squeeze=1.0, state=ExecutionState.STOPPED)
        assert not c.r.is_engaged
        # Re-latches here rather than rebasing against the pre-stop origin.
        np.testing.assert_allclose(
            c.frame((5.0, 0.0, 0.0), squeeze=1.0)[:3], [1.0, 0.0, 0.0], atol=1e-6
        )


class TestEngageRelativeClutchDisarm:
    """Dropped / invalid / degenerate frames hold the pose AND re-arm the pending latch.

    The happy-path tests never exercise these branches, so without this class the disarm logic --
    the half of the latch structure that a plain rising-edge boolean gets wrong -- would ship
    unverified behind a green suite.
    """

    def test_dropped_frame_holds_last_pose(self):
        c = _Driver()
        c.engage()
        held = c.frame((0.5, 0.0, 0.0)).copy()
        np.testing.assert_allclose(c.frame(present=False)[:3], held[:3], atol=1e-9)
        assert not c.r.is_engaged

    def test_invalid_grip_frame_holds_last_pose(self):
        c = _Driver()
        c.engage()
        held = c.frame((0.5, 0.0, 0.0)).copy()
        np.testing.assert_allclose(
            c.frame((9.0, 9.0, 9.0), grip_is_valid=False)[:3], held[:3], atol=1e-9
        )
        assert not c.r.is_engaged

    def test_degenerate_quaternion_frame_holds_last_pose(self):
        """A source that flags the pose valid yet emits a zero quaternion must not reach the IK."""
        c = _Driver()
        c.engage()
        held = c.frame((0.5, 0.0, 0.0)).copy()
        pose = c.frame((9.0, 9.0, 9.0), np.zeros(4))
        np.testing.assert_allclose(pose[:3], held[:3], atol=1e-9)
        assert np.all(np.isfinite(pose))
        assert not c.r.is_engaged

    def test_non_finite_grip_position_frame_holds_last_pose(self):
        """A NaN position on a valid-flagged frame must never reach the commanded pose.

        Once NaN enters the held pose it is unrecoverable: the hold path re-emits it, and the
        last-commanded home fallback re-latches it on the next engage. NaN comparisons are all
        False, so no downstream bounds check rejects it either.
        """
        c = _Driver()
        c.engage()
        held = c.frame((0.5, 0.0, 0.0)).copy()
        for bad in ((np.nan, 0.0, 0.0), (0.0, np.inf, 0.0), (0.0, 0.0, -np.inf)):
            pose = c.frame(bad)
            assert np.all(np.isfinite(pose)), f"non-finite output for grip_pos={bad}"
            np.testing.assert_allclose(pose[:3], held[:3], atol=1e-9)
            assert not c.r.is_engaged
        # ...and the clutch still works afterwards, from the pose it held.
        np.testing.assert_allclose(c.engage((5.0, 0.0, 0.0))[:3], held[:3], atol=1e-6)
        assert np.all(np.isfinite(c.r._last_commanded_pos))

    def test_invalid_frame_on_the_rising_edge_still_latches_next_frame(self):
        """An unusable frame defers the latch rather than consuming it."""
        c = _Driver()
        c.frame((0.0, 0.0, 0.0), squeeze=1.0)
        c.frame((1.0, 0.0, 0.0), squeeze=1.0)
        c.frame((1.0, 0.0, 0.0), squeeze=0.0)
        # The re-engage frame is invalid, so the latch stays owed...
        c.frame((9.0, 0.0, 0.0), squeeze=1.0, grip_is_valid=False)
        assert not c.r.is_engaged
        # ...and fires on the next good frame, holding rather than jumping to the controller.
        np.testing.assert_allclose(
            c.frame((9.0, 0.0, 0.0), squeeze=1.0)[:3], [1.0, 0.0, 0.0], atol=1e-6
        )

    def test_release_and_resqueeze_across_a_dropout_does_not_jump(self):
        """The case a plain rising-edge boolean gets wrong.

        The squeeze is unobservable during a dropout, so if the operator releases and re-squeezes
        inside the gap, no falling edge is ever *seen*. Keeping the old origin would rebase against
        the pre-dropout engagement and jump the arm by the whole accumulated hand motion. Disarming
        on the dropped frames keeps the latch owed, so the first good frame re-latches in place.
        """
        c = _Driver()
        c.frame((0.0, 0.0, 0.0), squeeze=1.0)
        c.frame((1.0, 0.0, 0.0), squeeze=1.0)
        for pos in ((3.0, 0.0, 0.0), (6.0, 0.0, 0.0), (9.0, 0.0, 0.0)):
            c.frame(pos, present=False)
        np.testing.assert_allclose(
            c.frame((9.0, 0.0, 0.0), squeeze=1.0)[:3], [1.0, 0.0, 0.0], atol=1e-6
        )


class TestEngageRelativeClutchMeasuredHome:
    """The asymmetric home latch: position from the measurement, orientation never."""

    def test_measured_pose_supplies_the_home_position(self):
        """An arm that sagged while disengaged is not snapped back to the stale command."""
        c = _Driver()
        c.engage()
        c.frame((1.0, 0.0, 0.0))
        pose = c.engage((5.0, 5.0, 5.0), measured=(0.30, 0.05, 0.09))
        np.testing.assert_allclose(pose[:3], [0.30, 0.05, 0.09], atol=1e-6)

    def test_measured_pose_does_not_supply_the_home_orientation(self):
        """Orientation always comes from the last commanded rotation -- never the measurement.

        The 5-DOF wrist tracks orientation softly, so latching the measured orientation would
        inject that tracking offset into the command on every re-clutch.
        """
        c = _Driver()
        c.engage()
        ctrl = _quat_xyzw([0.0, 0.0, 1.0], math.pi / 2)
        c.frame((0.0, 0.0, 0.0), ctrl)
        measured_rot = _quat_to_matrix(_quat_xyzw([1.0, 0.0, 0.0], math.pi / 3))
        tg = TensorGroup(TransformMatrix())
        tg[0] = _make_home_transform((0.4, 0.0, 0.0), measured_rot).astype(np.float32)
        c.frame((0.0, 0.0, 0.0), ctrl, squeeze=0.0)
        c.inputs[SO101ClutchRetargeter.MEASURED_BASE_T_EE_INPUT] = tg
        c.inputs[ControllersSource.RIGHT] = _make_controller(grip_ori=ctrl, squeeze=1.0)
        c.r.compute(c.inputs, c.outputs, _make_context())
        pose = _read_pose(c.outputs)
        np.testing.assert_allclose(
            pose[:3], [0.4, 0.0, 0.0], atol=1e-6
        )  # position: measured
        assert _rot_dist(pose[3:7], ctrl) < 1e-6  # orientation: last commanded

    def test_absent_measured_input_falls_back_to_the_last_commanded_position(self):
        """An unwired measured input lands on the last-commanded home, silently and repeatedly.

        This is a *designed* path, not degraded mode: a consumer whose owning task slews the arm
        to a known configured home on reset (Isaac Lab) legitimately leaves
        ``MEASURED_BASE_T_EE_INPUT`` unconnected, so the retargeter must not editorialize about
        it. The fallback is exercised across several re-clutches to pin that it stays stable
        rather than drifting or firing only once.
        """
        c = _Driver()
        c.engage()
        c.frame((1.0, 0.0, 0.0))
        np.testing.assert_allclose(
            c.engage((5.0, 5.0, 5.0))[:3], [1.0, 0.0, 0.0], atol=1e-6
        )
        c.frame((6.0, 5.0, 5.0))
        np.testing.assert_allclose(
            c.engage((7.0, 5.0, 5.0))[:3], [2.0, 0.0, 0.0], atol=1e-6
        )


class TestEngageRelativeClutchSetHome:
    """``set_home_base_T_ee`` -- the late-seeding path used when the graph is built before the
    arm is homed, and the transform a subsequent ``reset`` re-seeds to. Public API, so it is
    covered directly."""

    def test_set_home_reseeds_the_held_pose(self):
        c = _Driver(_make_home_transform((0.0, 0.0, 0.0)))
        home_rot = _quat_to_matrix(_quat_xyzw([0.0, 0.0, 1.0], math.pi / 2))
        c.r.set_home_base_T_ee(_make_home_transform((0.22, 0.0, 0.12), home_rot))
        pose = c.frame(squeeze=0.0)
        np.testing.assert_allclose(pose[:3], [0.22, 0.0, 0.12], atol=1e-6)
        assert _rot_dist(pose[3:7], _mat_to_quat_xyzw(home_rot)) < 1e-6

    def test_set_home_while_engaged_rearms_instead_of_jumping(self):
        """Re-seeding mid-engagement must not leave the OLD origin latched against the NEW home.

        Without the re-arm the next frame would command ``new_home + scale*(grip - old_origin)``,
        i.e. a jump of ``new_home - old_home`` at servo speed.
        """
        c = _Driver(_make_home_transform((0.0, 0.0, 0.0)))
        c.frame((0.0, 0.0, 0.0), squeeze=1.0)
        c.frame((1.0, 0.0, 0.0), squeeze=1.0)
        assert c.r.is_engaged

        c.r.set_home_base_T_ee(_make_home_transform((5.0, 0.0, 0.0)))
        assert not c.r.is_engaged, "set_home_base_T_ee must re-arm the pending latch"
        # The next engaged frame re-latches in place at the new home -- no accumulated delta.
        np.testing.assert_allclose(
            c.frame((1.0, 0.0, 0.0), squeeze=1.0)[:3], [5.0, 0.0, 0.0], atol=1e-6
        )


class TestEngageRelativeClutchPositionScale:
    """``position_scale`` validation and effect."""

    def test_scale_halves_the_delta_but_the_engage_frame_still_returns_home(self):
        c = _Driver(_make_home_transform((0.1, 0.2, 0.3)), position_scale=0.5)
        np.testing.assert_allclose(
            c.engage((5.0, -3.0, 2.0))[:3], [0.1, 0.2, 0.3], atol=1e-6
        )
        np.testing.assert_allclose(
            c.frame((5.4, -3.0, 2.0))[:3], [0.3, 0.2, 0.3], atol=1e-6
        )

    @pytest.mark.parametrize("scale", [0.0, -1.0, float("inf"), float("nan")])
    def test_invalid_scale_raises(self, scale):
        with pytest.raises(
            ValueError, match="position_scale must be positive and finite"
        ):
            SO101ClutchRetargeter(
                "c", _make_home_transform((0.0, 0.0, 0.0)), position_scale=scale
            )


class TestEngageRelativeClutchSqueezeThreshold:
    """``squeeze_threshold`` validation. Every rejected value fails the SAME way -- silently."""

    @pytest.mark.parametrize("threshold", [0.0, 0.5, 0.999])
    def test_valid_threshold_accepted(self, threshold):
        """The usable range is ``[0, 1)``; ``0`` engages on any non-zero squeeze."""
        c = _Driver(squeeze_threshold=threshold)
        c.frame((0.0, 0.0, 0.0), squeeze=1.0)
        assert c.r.is_engaged

    @pytest.mark.parametrize(
        "threshold", [float("nan"), 1.0, 1.5, float("inf"), -0.1, float("-inf")]
    )
    def test_invalid_threshold_raises(self, threshold):
        """A threshold outside ``[0, 1)`` can never be exceeded -- the clutch would never engage.

        ``NaN`` is the nastiest of these: every ``squeeze > NaN`` comparison is False, so the
        clutch stays disengaged forever with no error, no warning and a perfectly healthy-looking
        graph. A threshold of ``1.0`` or above is the same defect by a different route, since the
        squeeze axis is normalized to ``[0, 1]`` and the comparison is strict.
        """
        with pytest.raises(
            ValueError, match=r"squeeze_threshold must be finite and in \[0, 1\)"
        ):
            SO101ClutchRetargeter(
                "c",
                _make_home_transform((0.0, 0.0, 0.0)),
                squeeze_threshold=threshold,
            )


class TestEngageRelativeClutchHomeValidation:
    """``home_base_T_ee`` must be a 4x4 with a *proper* rotation block.

    A scaled or reflected block still converts to a unit quaternion, so it would command a quietly
    wrong home orientation with nothing downstream to reject it -- the one failure mode this class
    exists to make loud.
    """

    def test_scaled_rotation_block_rejected(self):
        home = _make_home_transform((0.1, 0.2, 0.3), 2.0 * np.eye(3))
        with pytest.raises(ValueError, match="orthonormal"):
            SO101ClutchRetargeter("c", home)

    def test_reflected_rotation_block_rejected(self):
        """Orthonormal but ``det == -1``: a reflection, not a rotation."""
        home = _make_home_transform((0.1, 0.2, 0.3), np.diag([1.0, 1.0, -1.0]))
        with pytest.raises(ValueError, match="proper rotation"):
            SO101ClutchRetargeter("c", home)

    def test_shear_rotation_block_rejected(self):
        home = _make_home_transform(
            (0.1, 0.2, 0.3),
            np.array([[1.0, 0.2, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]),
        )
        with pytest.raises(ValueError, match="orthonormal"):
            SO101ClutchRetargeter("c", home)

    def test_wrong_shape_rejected(self):
        with pytest.raises(ValueError, match="4x4"):
            SO101ClutchRetargeter("c", np.eye(3))

    def test_non_finite_rejected(self):
        home = _make_home_transform((np.nan, 0.2, 0.3))
        with pytest.raises(ValueError, match="finite"):
            SO101ClutchRetargeter("c", home)

    def test_legacy_positional_call_fails_loudly(self):
        """The retired signature put ``input_device`` second; that call must not silently work."""
        with pytest.raises(ValueError):
            SO101ClutchRetargeter("ee_pose", ControllersSource.RIGHT)

    def test_float32_rotation_block_accepted(self):
        """Callers routinely build the transform in float32; the tolerance must not reject it.

        Swept rather than sampled once: a single lucky draw would not show that the tolerance
        clears the *worst* float32 residual, and the check refusing a legitimate measured home is
        the failure this class would otherwise cause.
        """
        rng = np.random.default_rng(20260727)
        for _ in range(200):
            q = rng.standard_normal(4)
            rot = _quat_to_matrix(q / np.linalg.norm(q))
            home = _make_home_transform((0.1, 0.2, 0.3), rot).astype(np.float32)
            c = _Driver(home)
            np.testing.assert_allclose(
                c.frame(squeeze=0.0)[:3], [0.1, 0.2, 0.3], atol=1e-6
            )

    def test_hand_typed_rotation_block_accepted(self):
        """A matrix hand-typed at 5 decimal places must not be rejected as "not orthonormal".

        Hand-typed 4x4s are a supported caller input -- a home transform read off a sensor once and
        pasted into a config file is the ordinary way a task pins its seated pose -- so a tolerance
        that policed precision rather than structure would reject a legitimate home. 5 decimals is
        the documented floor (see ``_ROTATION_ATOL``); 4 is NOT covered and is rejected ~16% of the
        time.

        Swept rather than sampled once, for the same reason as
        :meth:`test_float32_rotation_block_accepted`: a single lucky draw says nothing about the
        worst rounding residual, which is the number the tolerance is actually sized against.
        """
        rng = np.random.default_rng(20260727)
        for _ in range(200):
            q = rng.standard_normal(4)
            rot = np.round(_quat_to_matrix(q / np.linalg.norm(q)), 5)
            c = _Driver(_make_home_transform((0.1, 0.2, 0.3), rot))
            np.testing.assert_allclose(
                c.frame(squeeze=0.0)[:3], [0.1, 0.2, 0.3], atol=1e-6
            )

    def test_transposed_transform_rejected(self):
        """``base_T_ee.T`` passes every other check, so the bottom row is the only guard.

        Its rotation block is ``R.T`` -- orthonormal, ``det == +1`` -- and the translation moves to
        the bottom row, leaving column 3 zeroed. Without this check the clutch would home at the
        base origin with the inverse orientation and report nothing.
        """
        rot = _quat_to_matrix(_quat_xyzw([1.0, 2.0, 3.0], 0.9))
        home = _make_home_transform((0.1, 0.2, 0.3), rot)
        with pytest.raises(ValueError, match="bottom row"):
            SO101ClutchRetargeter("c", home.T)

    def test_set_home_validates_too(self):
        """The late-seeding path is the one a live loop calls -- it gets the same guard."""
        c = _Driver()
        with pytest.raises(ValueError, match="orthonormal"):
            c.r.set_home_base_T_ee(
                _make_home_transform((0.0, 0.0, 0.0), np.zeros((3, 3)))
            )


class TestEngageRelativeClutchStatePrecision:
    """The float64 internal state, asserted white-box on purpose.

    The ``ee_pose`` output is float32 by contract, and that contract structurally HIDES this
    defect: an implementation that reads its running home back out of the emitted float32 pose --
    the obvious shortcut, since the pose is right there -- is pinned at ~1 float32 ULP in that
    same output under either state layout, so no black-box assertion can discriminate. Reaching
    into the
    float64 state attribute is the only instrument that can, and the error it catches grows with
    re-clutch count whenever no measured pose re-seeds the home.
    """

    def test_repeated_reclutch_does_not_quantize_the_commanded_pose(self):
        """50 re-clutches of an exactly-cancelling excursion must leave the state where it began.

        Both channels are exercised with values that MOVE: each cycle latches a different engage
        orientation and swings out through a non-identity rotation and an off-float32-grid
        translation before returning to the engage pose, so the commanded pose is analytically
        unchanged only after passing through states float32 cannot represent.

        Scope: the measured-EE input is deliberately absent throughout. ``TransformMatrix`` is
        float32 *by tensor type*, so feeding it would re-seed the home at float32 resolution and
        this assertion would measure that quantization rather than the state layout. The
        orientation channel has no measured re-seed path at all -- it always comes from the last
        commanded rotation -- which is exactly why float64 state is load-bearing there.

        This test's whole job is to catch the float32-state defect, so it is written to be capable
        of failing: driving the same sequence through a state that round-trips via the float32
        output scores ~1e-07 m and ~1e-06 in these metrics, orders above both thresholds.
        """
        start = np.array([0.1234567890123, -0.9876543210987, 0.5555555555555])
        # The seeded home rotation must NOT be float32-representable, or the orientation half of
        # this test is vacuous: identity survives a float32 round-trip exactly, so a quantizing
        # state layout would score zero against it.
        start_rot = _quat_to_matrix(
            _quat_xyzw([0.31234567, -0.7654321, 0.5555511], 0.9876543)
        )
        c = _Driver(_make_home_transform(start, start_rot))
        home_rot0 = c.r._last_commanded_rot.copy()
        assert not np.array_equal(
            home_rot0, home_rot0.astype(np.float32).astype(np.float64)
        ), "seed rotation must not be exactly float32-representable"
        delta = np.array([math.pi, math.e, math.sqrt(2)]) * 1e-3

        for k in range(50):
            # A different engage orientation every cycle, so _home_rot re-latches onto a moving
            # target instead of sitting on identity (which would assert nothing).
            engage_q = _quat_xyzw([1.0, 2.0, 3.0], 0.017 * (k + 1))
            swing_q = _quat_xyzw([-2.0, 1.0, 0.5], 0.023 * (k + 1))
            c.frame((0.0, 0.0, 0.0), engage_q, squeeze=0.0)
            c.frame((0.0, 0.0, 0.0), engage_q, squeeze=1.0)
            c.frame(tuple(delta), swing_q)  # out, through an unrepresentable pose
            c.frame((0.0, 0.0, 0.0), engage_q)  # and exactly back

        assert float(np.max(np.abs(c.r._last_commanded_pos - start))) == 0.0
        # Each cycle ends on q_engage (x) q_engage^-1 (x) R_home == R_home, and R_home is
        # re-latched from that same value next cycle -- so the rotation returns to the seed.
        assert _rot_dist(c.r._last_commanded_rot, home_rot0) < 1e-12


class TestEngageRelativeClutchPipelineShape:
    """The in-pipeline wiring contract the LeRobot example depends on.

    That example cannot be exercised by this suite (different repo, and its pinned ``isaacteleop``
    predates this retargeter), so the graph shape it builds is covered here instead.
    """

    def _build_graph(self, retargeter):
        controllers = ValueInput("controllers", OptionalType(ControllerInput()))
        measured = ValueInput("measured_ee", OptionalType(TransformMatrix()))
        sub = retargeter.connect(
            {
                ControllersSource.RIGHT: controllers.output("value"),
                SO101ClutchRetargeter.MEASURED_BASE_T_EE_INPUT: measured.output(
                    "value"
                ),
            }
        )
        # The raw controller stays on the combiner: the device derives is_tracking and the analog
        # trigger from it, and both would be lost if only ee_pose were published.
        return OutputCombiner(
            {
                "ee_pose": sub.output("ee_pose"),
                "controller": controllers.output("value"),
            }
        )

    def test_graph_executes_and_publishes_both_outputs(self):
        r = SO101ClutchRetargeter(
            "clutch", _make_home_transform((0.0, 0.0, 0.0)), position_scale=0.5
        )
        graph = self._build_graph(r)
        result = graph.execute_pipeline(
            {
                "controllers": {"value": _make_controller(squeeze=1.0)},
                "measured_ee": {"value": _make_measured((0.30, 0.05, 0.09))},
            },
            context=_make_context(),
        )
        np.testing.assert_allclose(
            np.from_dlpack(result["ee_pose"][0])[:3], [0.30, 0.05, 0.09], atol=1e-6
        )
        assert r.is_engaged
        # is_tracking regression: the device re-derives it from this group's is_none. If that
        # derivation is lost, the example's connect-wait loop never returns.
        assert result["controller"].is_none is False
        assert float(result["controller"][ControllerInputIndex.TRIGGER_VALUE]) == 0.0

    def test_untracked_controller_holds_pose_and_reports_is_none(self):
        r = SO101ClutchRetargeter("clutch", _make_home_transform((0.2, 0.0, 0.1)))
        graph = self._build_graph(r)
        result = graph.execute_pipeline(
            {"controllers": {"value": OptionalTensorGroup(ControllerInput())}},
            context=_make_context(),
        )
        np.testing.assert_allclose(
            np.from_dlpack(result["ee_pose"][0])[:3], [0.2, 0.0, 0.1], atol=1e-6
        )
        assert result["controller"].is_none is True
        assert not r.is_engaged

    def test_measured_value_input_must_be_declared_optional(self):
        """A plain ``ValueInput`` leaf is REQUIRED and raises inside the retargeting worker.

        ``ValueInput.input_spec`` returns a plain ``TensorGroupType``, so a leaf that is not fed
        every step fails the graph rather than degrading. Declaring it ``OptionalType`` is what
        makes a skipped feed land on the documented last-commanded fallback instead of a
        ``RuntimeError`` at frame rate with the arm live.
        """
        r = SO101ClutchRetargeter("clutch", _make_home_transform((0.0, 0.0, 0.0)))
        controllers = ValueInput("controllers", OptionalType(ControllerInput()))
        strict = ValueInput("measured_ee", TransformMatrix())  # NOT OptionalType
        graph = OutputCombiner(
            {
                "ee_pose": r.connect(
                    {
                        ControllersSource.RIGHT: controllers.output("value"),
                        SO101ClutchRetargeter.MEASURED_BASE_T_EE_INPUT: strict.output(
                            "value"
                        ),
                    }
                ).output("ee_pose")
            }
        )
        with pytest.raises(ValueError, match="not found in cache"):
            graph.execute_pipeline(
                {"controllers": {"value": _make_controller(squeeze=1.0)}},
                context=_make_context(),
            )
        # The optional form, by contrast, runs clean when unfed.
        optional_graph = self._build_graph(
            SO101ClutchRetargeter("clutch2", _make_home_transform((0.2, 0.0, 0.1)))
        )
        result = optional_graph.execute_pipeline(
            {"controllers": {"value": _make_controller(squeeze=1.0)}},
            context=_make_context(),
        )
        np.testing.assert_allclose(
            np.from_dlpack(result["ee_pose"][0])[:3], [0.2, 0.0, 0.1], atol=1e-6
        )
