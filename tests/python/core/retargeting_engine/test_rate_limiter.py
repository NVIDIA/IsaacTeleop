# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Sim-free unit tests for the rate-limiting safety harness retargeters.

Covers the safety-harness nodes that bound per-frame command velocity for bare
position-servo followers (e.g. the SO-101):

* :class:`~isaacteleop.retargeters.EePoseRateLimiter` -- linear/angular velocity
  bounds on an absolute 7-D ``ee_pose`` stream.
* :class:`~isaacteleop.retargeters.JointRateLimiter` -- per-joint velocity bounds
  on a name-keyed ``joint_targets`` group.

Each limiter is exercised at the pure-math level (the module-private clamp
helpers) and at the ``BaseRetargeter.compute`` level (build inputs/outputs, drive
frames with controlled ``GraphTime`` stamps, read the emitted tensors), with no
``gym.make``, USD, GPU, or XR device.
"""

import math

import numpy as np
import pytest

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
from isaacteleop.retargeters import (
    EePoseRateLimiter,
    JointRateLimiter,
    RateLimiterConfig,
)
from isaacteleop.retargeters.rate_limiter import (
    EE_POSE_KEY,
    JOINT_TARGETS_KEY,
    _clamp_orientation_step,
    _clamp_position_step,
    _clamped_dt,
)

# ---------------------------------------------------------------------------
# Helpers (mirror the patterns in test_so101_retargeters.py)
# ---------------------------------------------------------------------------

_ID_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
_NS = 1_000_000_000


def _make_context(
    *,
    reset: bool = False,
    state: ExecutionState = ExecutionState.RUNNING,
    t_ns: int = 0,
) -> ComputeContext:
    """Build a ComputeContext with the given reset flag, state, and timestamp."""
    return ComputeContext(
        graph_time=GraphTime(sim_time_ns=t_ns, real_time_ns=t_ns),
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


def _pose_group(spec_type, pos, ori=_ID_QUAT) -> TensorGroup:
    """Build a present 7-D ee_pose TensorGroup from a position and quaternion."""
    tg = TensorGroup(spec_type.inner_type)
    tg[0] = np.concatenate(
        [np.asarray(pos, dtype=np.float32), np.asarray(ori, dtype=np.float32)]
    )
    return tg


def _set_pose_input(limiter, inputs, pos, ori=_ID_QUAT) -> None:
    """Replace the limiter's ee_pose input with a present pose group."""
    spec = limiter.input_spec()[EE_POSE_KEY]
    inputs[EE_POSE_KEY] = _pose_group(spec, pos, ori)


def _set_joint_input(limiter, inputs, values) -> None:
    """Replace the limiter's joint_targets input with a present group."""
    spec = limiter.input_spec()[JOINT_TARGETS_KEY]
    tg = TensorGroup(spec.inner_type)
    for i, v in enumerate(values):
        tg[i] = float(v)
    inputs[JOINT_TARGETS_KEY] = tg


def _read_pose(outputs) -> np.ndarray:
    """Read the 7-D ee_pose output as a numpy array."""
    return np.asarray(np.from_dlpack(outputs[EE_POSE_KEY][0]), dtype=np.float64)


def _read_joints(outputs, n: int) -> np.ndarray:
    """Read the joint_targets output as a numpy array."""
    return np.array(
        [float(outputs[JOINT_TARGETS_KEY][i]) for i in range(n)], dtype=np.float64
    )


def _quat_xyzw(axis, angle_rad: float) -> np.ndarray:
    """Build an [x, y, z, w] quaternion for a rotation of ``angle_rad`` about ``axis``."""
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    half = 0.5 * angle_rad
    xyz = axis * math.sin(half)
    return np.array([xyz[0], xyz[1], xyz[2], math.cos(half)], dtype=np.float64)


def _quat_angle(a: np.ndarray, b: np.ndarray) -> float:
    """Geodesic angle [rad] between two unit quaternions (double-cover aware)."""
    dot = abs(float(np.dot(a, b)))
    return 2.0 * math.acos(min(1.0, dot))


# ===========================================================================
# Pure math helpers
# ===========================================================================


class TestClampedDt:
    """The ``_clamped_dt`` frame-delta helper."""

    def test_no_previous_uses_nominal(self):
        """With no previous stamp the nominal dt is returned."""
        assert _clamped_dt(None, 123, 0.02, 1e-4, 0.1) == pytest.approx(0.02)

    def test_duplicate_stamp_uses_nominal(self):
        """A non-advancing clock falls back to the nominal dt (no frozen limiter)."""
        assert _clamped_dt(500, 500, 0.02, 1e-4, 0.1) == pytest.approx(0.02)
        assert _clamped_dt(500, 400, 0.02, 1e-4, 0.1) == pytest.approx(0.02)

    def test_normal_delta_passes(self):
        """A delta within [min_dt, max_dt] is returned as-is."""
        assert _clamped_dt(0, 20_000_000, 0.02, 1e-4, 0.1) == pytest.approx(0.02)

    def test_stall_clamps_to_max(self):
        """A multi-second stall is clamped to max_dt (no huge authorized step)."""
        assert _clamped_dt(0, 5 * _NS, 0.02, 1e-4, 0.1) == pytest.approx(0.1)

    def test_tiny_delta_clamps_to_min(self):
        """A near-zero delta is clamped up to min_dt."""
        assert _clamped_dt(0, 10, 0.02, 1e-4, 0.1) == pytest.approx(1e-4)


class TestClampPositionStep:
    """The ``_clamp_position_step`` Euclidean step clamp."""

    def test_within_limit_passes_through(self):
        """A step under the limit is returned untouched."""
        prev = np.zeros(3)
        tgt = np.array([0.001, 0.0, 0.0])
        out = _clamp_position_step(tgt, prev, 0.01)
        np.testing.assert_allclose(out, tgt)

    def test_over_limit_is_clamped_along_line(self):
        """An over-limit step lands exactly max_step along the straight line."""
        prev = np.zeros(3)
        tgt = np.array([1.0, 0.0, 0.0])
        out = _clamp_position_step(tgt, prev, 0.01)
        np.testing.assert_allclose(out, [0.01, 0.0, 0.0], atol=1e-12)

    def test_zero_step_is_stable(self):
        """target == previous returns target (no divide-by-zero)."""
        p = np.array([0.2, 0.1, 0.3])
        out = _clamp_position_step(p.copy(), p.copy(), 0.01)
        np.testing.assert_allclose(out, p)


class TestClampOrientationStep:
    """The ``_clamp_orientation_step`` geodesic rotation clamp."""

    def test_within_limit_passes_through(self):
        """A rotation under the limit reaches the target orientation."""
        tgt = _quat_xyzw([0, 0, 1], 0.01)
        out = _clamp_orientation_step(tgt, _ID_QUAT.copy(), 0.1)
        assert _quat_angle(out, tgt) == pytest.approx(0.0, abs=1e-9)

    def test_over_limit_advances_exactly_max_step(self):
        """An over-limit rotation advances exactly max_step along the arc."""
        tgt = _quat_xyzw([0, 0, 1], 1.0)
        out = _clamp_orientation_step(tgt, _ID_QUAT.copy(), 0.1)
        assert _quat_angle(out, _ID_QUAT) == pytest.approx(0.1, abs=1e-9)

    def test_double_cover_takes_shortest_arc(self):
        """A sign-flipped target quaternion still rotates along the shortest arc."""
        tgt = -_quat_xyzw([0, 0, 1], 1.0)  # same rotation, other hemisphere
        out = _clamp_orientation_step(tgt, _ID_QUAT.copy(), 0.1)
        assert _quat_angle(out, _ID_QUAT) == pytest.approx(0.1, abs=1e-9)

    def test_identity_step_is_stable(self):
        """target == previous is returned without axis extraction blowing up."""
        q = _quat_xyzw([0, 1, 0], 0.3)
        out = _clamp_orientation_step(q.copy(), q.copy(), 0.1)
        # acos-based angle recovery amplifies float rounding near 0; 1e-6 rad is
        # far below any meaningful command resolution.
        assert _quat_angle(out, q) == pytest.approx(0.0, abs=1e-6)


# ===========================================================================
# RateLimiterConfig validation
# ===========================================================================


class TestRateLimiterConfig:
    """Constructor validation of the shared config."""

    def test_defaults_are_valid(self):
        """The default config constructs without error."""
        RateLimiterConfig()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_linear_velocity": 0.0},
            {"max_angular_velocity": -1.0},
            {"max_joint_velocity": 0.0},
            {"joint_velocity_overrides": {"elbow": 0.0}},
            {"min_dt": 0.0},
            {"min_dt": 0.05, "nominal_dt": 0.02},
            {"nominal_dt": 0.2, "max_dt": 0.1},
            {"reject_linear_velocity": 0.0},
            {"reject_linear_velocity": float("nan")},
            # Rejection threshold below the clamp limit would refuse motion the
            # clamp band is meant to allow.
            {"max_linear_velocity": 0.25, "reject_linear_velocity": 0.1},
            {"max_angular_velocity": 1.5, "reject_angular_velocity": 1.0},
            {"max_joint_velocity": 1.5, "reject_joint_velocity": 1.0},
            # ... including per-joint overrides above the rejection threshold.
            {
                "joint_velocity_overrides": {"elbow": 5.0},
                "reject_joint_velocity": 4.0,
            },
            {"max_consecutive_rejections": 0},
        ],
    )
    def test_invalid_values_raise(self, kwargs):
        """Non-positive limits and inconsistent dt/rejection bounds are rejected."""
        with pytest.raises(ValueError):
            RateLimiterConfig(**kwargs)

    def test_rejection_thresholds_accept_valid_values(self):
        """Rejection thresholds at or above the clamp limits construct fine."""
        RateLimiterConfig(
            reject_linear_velocity=0.25,
            reject_angular_velocity=1.5,
            reject_joint_velocity=1.5,
            max_consecutive_rejections=None,
        )


# ===========================================================================
# EePoseRateLimiter
# ===========================================================================


class TestEePoseRateLimiter:
    """End-to-end ``compute`` behavior of the EE-pose limiter."""

    def _limiter(self, **cfg_kwargs) -> EePoseRateLimiter:
        cfg = RateLimiterConfig(**cfg_kwargs) if cfg_kwargs else RateLimiterConfig()
        return EePoseRateLimiter(name="ee_limiter", config=cfg)

    def test_first_frame_passes_through(self):
        """The first valid frame latches and is emitted unclamped."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.3, 0.1, 0.2])
        r.compute(inputs, outputs, _make_context(t_ns=0))
        np.testing.assert_allclose(_read_pose(outputs)[:3], [0.3, 0.1, 0.2], atol=1e-6)

    def test_slow_motion_is_untouched(self):
        """Motion under the velocity limit is emitted exactly (no lag)."""
        r = self._limiter(max_linear_velocity=0.25)
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.2, 0.0, 0.1])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # 1 mm in 20 ms = 0.05 m/s, well under the 0.25 m/s limit.
        _set_pose_input(r, inputs, [0.201, 0.0, 0.1])
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(
            _read_pose(outputs)[:3], [0.201, 0.0, 0.1], atol=1e-6
        )

    def test_position_jump_is_rate_limited(self):
        """A teleport-sized position jump advances only max_linear_velocity * dt."""
        r = self._limiter(max_linear_velocity=0.25)
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # 0.5 m jump in 20 ms -> clamp to 0.25 * 0.02 = 5 mm.
        _set_pose_input(r, inputs, [0.5, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(
            _read_pose(outputs)[:3], [0.005, 0.0, 0.0], atol=1e-6
        )

    def test_persistent_target_is_approached_at_bounded_speed(self):
        """A held far target is approached stepwise, never faster than the limit."""
        r = self._limiter(max_linear_velocity=0.25)
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        last = np.zeros(3)
        for k in range(1, 6):
            _set_pose_input(r, inputs, [0.5, 0.0, 0.0])
            r.compute(inputs, outputs, _make_context(t_ns=k * 20_000_000))
            pos = _read_pose(outputs)[:3]
            step = float(np.linalg.norm(pos - last))
            assert step <= 0.25 * 0.02 + 1e-9
            last = pos
        # Monotonic progress toward the target.
        assert last[0] == pytest.approx(5 * 0.005, abs=1e-6)

    def test_orientation_jump_is_rate_limited(self):
        """A large orientation flip advances only max_angular_velocity * dt."""
        r = self._limiter(max_angular_velocity=1.5)
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.2, 0.0, 0.1], _ID_QUAT)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # pi/2 flip in 20 ms -> clamp to 1.5 * 0.02 = 0.03 rad.
        tgt = _quat_xyzw([0, 0, 1], math.pi / 2)
        _set_pose_input(r, inputs, [0.2, 0.0, 0.1], tgt)
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        emitted = _read_pose(outputs)[3:7]
        # The emitted pose is float32; angle recovery through acos loses a few
        # ulps, so compare at 1e-4 rad (~0.006 deg), far below command resolution.
        assert _quat_angle(emitted, _ID_QUAT) == pytest.approx(0.03, abs=1e-4)

    def test_stall_does_not_authorize_teleport(self):
        """A 5 s pipeline stall authorizes at most max_linear_velocity * max_dt."""
        r = self._limiter(max_linear_velocity=0.25, max_dt=0.1)
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        _set_pose_input(r, inputs, [1.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=5 * _NS))
        # 0.25 m/s * 0.1 s = 25 mm, not 1 m.
        np.testing.assert_allclose(
            _read_pose(outputs)[:3], [0.025, 0.0, 0.0], atol=1e-6
        )

    def test_dropped_frame_holds_last(self):
        """An absent input frame re-emits the last limited pose."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.3, 0.1, 0.2])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        inputs2, outputs2 = _build_io(r)  # optionals start absent
        r.compute(inputs2, outputs2, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(_read_pose(outputs2)[:3], [0.3, 0.1, 0.2], atol=1e-6)

    def test_reset_relatches_without_clamping(self):
        """After a reset the next frame passes through instead of slewing from the old pose."""
        r = self._limiter(max_linear_velocity=0.25)
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # Reset, then a far-away pose (the task has physically reset the arm).
        _set_pose_input(r, inputs, [0.4, 0.2, 0.1])
        r.compute(inputs, outputs, _make_context(reset=True, t_ns=20_000_000))
        np.testing.assert_allclose(_read_pose(outputs)[:3], [0.4, 0.2, 0.1], atol=1e-6)

    def test_degenerate_orientation_holds_previous(self):
        """A zero quaternion in the target holds the last emitted orientation."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        start_ori = _quat_xyzw([0, 1, 0], 0.2)
        _set_pose_input(r, inputs, [0.2, 0.0, 0.1], start_ori)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        _set_pose_input(r, inputs, [0.2, 0.0, 0.1], np.zeros(4))
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        emitted = _read_pose(outputs)[3:7]
        assert _quat_angle(emitted, start_ori) == pytest.approx(0.0, abs=1e-6)


# ===========================================================================
# JointRateLimiter
# ===========================================================================

_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]


class TestJointRateLimiter:
    """End-to-end ``compute`` behavior of the joint-space limiter."""

    def _limiter(self, **cfg_kwargs) -> JointRateLimiter:
        cfg = RateLimiterConfig(**cfg_kwargs) if cfg_kwargs else RateLimiterConfig()
        return JointRateLimiter(name="joint_limiter", joint_names=_JOINTS, config=cfg)

    def test_empty_joint_names_raises(self):
        """An empty joint list is rejected at construction."""
        with pytest.raises(ValueError):
            JointRateLimiter(name="bad", joint_names=[])

    def test_unknown_override_raises(self):
        """A velocity override for a joint not in joint_names is rejected."""
        with pytest.raises(ValueError):
            JointRateLimiter(
                name="bad",
                joint_names=["a"],
                config=RateLimiterConfig(joint_velocity_overrides={"zz": 1.0}),
            )

    def test_first_frame_passes_through(self):
        """The first valid frame latches and is emitted unclamped."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.1, -0.5, 1.2, 0.0, 0.3])
        r.compute(inputs, outputs, _make_context(t_ns=0))
        np.testing.assert_allclose(
            _read_joints(outputs, 5), [0.1, -0.5, 1.2, 0.0, 0.3], atol=1e-6
        )

    def test_slow_motion_is_untouched(self):
        """Per-joint motion under the limit is emitted exactly."""
        r = self._limiter(max_joint_velocity=1.5)
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # 0.01 rad in 20 ms = 0.5 rad/s, under the 1.5 rad/s limit.
        _set_joint_input(r, inputs, [0.01] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(_read_joints(outputs, 5), [0.01] * 5, atol=1e-6)

    def test_jump_is_rate_limited_per_joint(self):
        """An over-limit jump advances each joint by at most limit * dt, signed."""
        r = self._limiter(max_joint_velocity=1.5)
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # +-2 rad jumps in 20 ms -> clamp to +-1.5 * 0.02 = +-0.03 rad.
        _set_joint_input(r, inputs, [2.0, -2.0, 2.0, -2.0, 2.0])
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(
            _read_joints(outputs, 5), [0.03, -0.03, 0.03, -0.03, 0.03], atol=1e-6
        )

    def test_per_joint_override_applies(self):
        """A per-joint override clamps that joint tighter than the default."""
        r = self._limiter(
            max_joint_velocity=1.5,
            joint_velocity_overrides={"shoulder_lift": 0.5},
        )
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        _set_joint_input(r, inputs, [2.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        joints = _read_joints(outputs, 5)
        assert joints[1] == pytest.approx(0.5 * 0.02, abs=1e-6)  # overridden
        assert joints[0] == pytest.approx(1.5 * 0.02, abs=1e-6)  # default

    def test_dropped_frame_holds_last(self):
        """An absent input frame re-emits the last limited targets."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.1, 0.2, 0.3, 0.4, 0.5])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        inputs2, outputs2 = _build_io(r)  # optionals start absent
        r.compute(inputs2, outputs2, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(
            _read_joints(outputs2, 5), [0.1, 0.2, 0.3, 0.4, 0.5], atol=1e-6
        )

    def test_reset_relatches_without_clamping(self):
        """After a reset the next frame passes through (fresh episode, fresh baseline)."""
        r = self._limiter(max_joint_velocity=1.5)
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        _set_joint_input(r, inputs, [1.0, -1.0, 0.5, -0.5, 0.2])
        r.compute(inputs, outputs, _make_context(reset=True, t_ns=20_000_000))
        np.testing.assert_allclose(
            _read_joints(outputs, 5), [1.0, -1.0, 0.5, -0.5, 0.2], atol=1e-6
        )

    def test_stall_does_not_authorize_jump(self):
        """A long stall authorizes at most limit * max_dt per joint."""
        r = self._limiter(max_joint_velocity=1.5, max_dt=0.1)
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        _set_joint_input(r, inputs, [3.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=10 * _NS))
        np.testing.assert_allclose(_read_joints(outputs, 5), [0.15] * 5, atol=1e-6)


# ===========================================================================
# Anomaly rejection (reject_* thresholds)
# ===========================================================================


class TestEePoseAnomalyRejection:
    """Rejection tier of the EE-pose limiter: anomalous frames are not executed."""

    def _limiter(self, **cfg_kwargs) -> EePoseRateLimiter:
        cfg = RateLimiterConfig(
            max_linear_velocity=0.25,
            reject_linear_velocity=2.0,
            reject_angular_velocity=10.0,
            **cfg_kwargs,
        )
        return EePoseRateLimiter(name="ee_limiter", config=cfg)

    def test_anomalous_position_jump_is_not_approached(self):
        """A teleport beyond the reject envelope holds the pose entirely (no slew)."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # 0.5 m in 20 ms = 25 m/s >> 2 m/s reject threshold: hold, do not creep.
        _set_pose_input(r, inputs, [0.5, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(_read_pose(outputs)[:3], [0.0, 0.0, 0.0], atol=1e-6)

    def test_anomalous_orientation_flip_is_not_approached(self):
        """An orientation teleport beyond the reject envelope holds entirely."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.2, 0.0, 0.1], _ID_QUAT)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # pi rad in 20 ms = ~157 rad/s >> 10 rad/s reject threshold.
        tgt = _quat_xyzw([0, 0, 1], math.pi - 0.01)
        _set_pose_input(r, inputs, [0.2, 0.0, 0.1], tgt)
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        emitted = _read_pose(outputs)[3:7]
        assert _quat_angle(emitted, _ID_QUAT) == pytest.approx(0.0, abs=1e-6)

    def test_fast_but_legal_motion_is_clamped_not_rejected(self):
        """Motion between the clamp and reject thresholds is clamped, not refused."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # 20 mm in 20 ms = 1 m/s: above the 0.25 m/s clamp, below the 2 m/s
        # reject threshold -> the clamp band handles it (5 mm step).
        _set_pose_input(r, inputs, [0.02, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(
            _read_pose(outputs)[:3], [0.005, 0.0, 0.0], atol=1e-6
        )

    def test_glitch_recovery_resumes_from_held_pose(self):
        """After a one-frame teleport glitch, sane frames resume without a jump."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.1, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # Glitch frame: rejected, held at 0.1.
        _set_pose_input(r, inputs, [0.9, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(_read_pose(outputs)[:3], [0.1, 0.0, 0.0], atol=1e-6)

        # Recovery frame near the pre-glitch input: accepted, small step allowed.
        _set_pose_input(r, inputs, [0.101, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=40_000_000))
        np.testing.assert_allclose(
            _read_pose(outputs)[:3], [0.101, 0.0, 0.0], atol=1e-6
        )

    def test_persistent_target_reaccepted_after_cap(self):
        """After max_consecutive_rejections the far target is re-accepted, clamped."""
        r = self._limiter(max_consecutive_rejections=3)
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # 3 rejected frames, then the 4th trips the cap and re-accepts.
        for k in range(1, 4):
            _set_pose_input(r, inputs, [0.5, 0.0, 0.0])
            r.compute(inputs, outputs, _make_context(t_ns=k * 20_000_000))
            np.testing.assert_allclose(
                _read_pose(outputs)[:3], [0.0, 0.0, 0.0], atol=1e-6
            )
        _set_pose_input(r, inputs, [0.5, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=4 * 20_000_000))
        pos = _read_pose(outputs)[:3]
        # Re-accepted but still clamped: at most max_linear_velocity * max_dt.
        assert 0.0 < pos[0] <= 0.25 * 0.1 + 1e-9

    def test_cap_none_holds_indefinitely(self):
        """With max_consecutive_rejections=None an anomalous stream never executes."""
        r = self._limiter(max_consecutive_rejections=None)
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        for k in range(1, 100):
            _set_pose_input(r, inputs, [0.5, 0.0, 0.0])
            r.compute(inputs, outputs, _make_context(t_ns=k * 20_000_000))
            np.testing.assert_allclose(
                _read_pose(outputs)[:3], [0.0, 0.0, 0.0], atol=1e-6
            )

    def test_reset_clears_rejection_state(self):
        """A reset drops the rejection baseline: the next frame latches fresh."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        _set_pose_input(r, inputs, [0.9, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))  # rejected

        # Reset: the same far pose is now a fresh episode's first frame.
        _set_pose_input(r, inputs, [0.9, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(reset=True, t_ns=40_000_000))
        np.testing.assert_allclose(_read_pose(outputs)[:3], [0.9, 0.0, 0.0], atol=1e-6)

    def test_rejection_disabled_by_default(self):
        """Without reject thresholds a teleport is clamped (legacy behavior), not refused."""
        r = EePoseRateLimiter(
            name="ee_limiter", config=RateLimiterConfig(max_linear_velocity=0.25)
        )
        inputs, outputs = _build_io(r)
        _set_pose_input(r, inputs, [0.0, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=0))

        _set_pose_input(r, inputs, [0.5, 0.0, 0.0])
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(
            _read_pose(outputs)[:3], [0.005, 0.0, 0.0], atol=1e-6
        )


class TestJointAnomalyRejection:
    """Rejection tier of the joint limiter: anomalous frames are not executed."""

    def _limiter(self, **cfg_kwargs) -> JointRateLimiter:
        cfg = RateLimiterConfig(
            max_joint_velocity=1.5,
            reject_joint_velocity=15.0,
            **cfg_kwargs,
        )
        return JointRateLimiter(name="joint_limiter", joint_names=_JOINTS, config=cfg)

    def test_anomalous_flip_is_not_approached(self):
        """An IK-divergence-sized flip (>> reject threshold) holds all joints."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # ~100 deg (1.75 rad) in 20 ms = 87 rad/s >> 15 rad/s: refuse outright.
        _set_joint_input(r, inputs, [1.75] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(_read_joints(outputs, 5), [0.0] * 5, atol=1e-6)

    def test_single_bad_joint_rejects_whole_frame(self):
        """One joint over the reject threshold refuses the whole frame."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # Joints move together: executing the sane joints of an insane frame
        # still produces an insane configuration.
        _set_joint_input(r, inputs, [0.01, 0.01, 1.75, 0.01, 0.01])
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(_read_joints(outputs, 5), [0.0] * 5, atol=1e-6)

    def test_fast_but_legal_motion_is_clamped_not_rejected(self):
        """Motion between the clamp and reject thresholds is clamped, not refused."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        # 0.1 rad in 20 ms = 5 rad/s: above the 1.5 rad/s clamp, below the
        # 15 rad/s reject threshold -> clamped to 0.03 rad.
        _set_joint_input(r, inputs, [0.1] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(_read_joints(outputs, 5), [0.03] * 5, atol=1e-6)

    def test_glitch_recovery_resumes_from_held_targets(self):
        """After a one-frame glitch, sane frames resume without a jump."""
        r = self._limiter()
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.1] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        _set_joint_input(r, inputs, [1.75] * 5)  # glitch: rejected
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(_read_joints(outputs, 5), [0.1] * 5, atol=1e-6)

        _set_joint_input(r, inputs, [0.11] * 5)  # recovery: accepted
        r.compute(inputs, outputs, _make_context(t_ns=40_000_000))
        np.testing.assert_allclose(_read_joints(outputs, 5), [0.11] * 5, atol=1e-6)

    def test_persistent_target_reaccepted_after_cap(self):
        """After max_consecutive_rejections the far target is re-accepted, clamped."""
        r = self._limiter(max_consecutive_rejections=2)
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        for k in range(1, 3):
            _set_joint_input(r, inputs, [1.75] * 5)
            r.compute(inputs, outputs, _make_context(t_ns=k * 20_000_000))
            np.testing.assert_allclose(_read_joints(outputs, 5), [0.0] * 5, atol=1e-6)

        _set_joint_input(r, inputs, [1.75] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=3 * 20_000_000))
        joints = _read_joints(outputs, 5)
        # Re-accepted but still clamped: at most max_joint_velocity * max_dt.
        assert np.all(joints > 0.0)
        assert np.all(joints <= 1.5 * 0.1 + 1e-9)

    def test_rejection_disabled_by_default(self):
        """Without reject_joint_velocity a flip is clamped (legacy behavior)."""
        r = JointRateLimiter(
            name="joint_limiter",
            joint_names=_JOINTS,
            config=RateLimiterConfig(max_joint_velocity=1.5),
        )
        inputs, outputs = _build_io(r)
        _set_joint_input(r, inputs, [0.0] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=0))

        _set_joint_input(r, inputs, [1.75] * 5)
        r.compute(inputs, outputs, _make_context(t_ns=20_000_000))
        np.testing.assert_allclose(_read_joints(outputs, 5), [0.03] * 5, atol=1e-6)
