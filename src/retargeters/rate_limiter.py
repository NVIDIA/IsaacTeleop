# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Rate-limiting safety harness retargeters (EE-pose and joint-space).

Low-cost follower arms such as the SO-101 run bare position servos with no
controller-side handling of anomalous targets: whatever position command reaches the
bus is tracked at full servo torque. A single bad frame -- an IK jump near a
singularity, a controller tracking glitch, a leader-stream hiccup, an operator
flick -- becomes a full-speed slew that can strip gears or stall motors on real
hardware.

This module provides two composable harness nodes that bound the *step per frame*
of an existing command stream without changing its contract, so they can be
inserted between a producing retargeter and the downstream action wiring:

* :class:`EePoseRateLimiter` -- wraps a 7-D absolute ``ee_pose`` stream (e.g. the
  output of ``SO101ClutchRetargeter`` or ``Se3AbsRetargeter``), clamping linear
  velocity [m/s] and angular velocity [rad/s].
* :class:`JointRateLimiter` -- wraps a name-keyed joint-target group (e.g. the
  ``joint`` mode output of ``JointStateRetargeter``), clamping per-joint velocity
  [rad/s or m/s], with optional per-joint overrides.

Both limiters are pure trajectory governors:

- The **first valid frame** after construction or a pipeline reset passes through
  unclamped and latches the baseline. Engage-time placement is owned by the
  upstream clutch / align logic (which already guarantees no snap on engage); the
  limiter bounds *motion between frames*, not absolute placement.
- Each subsequent frame may move at most ``max_velocity * dt`` from the last
  *emitted* command (not the last input), so a persistent far-away target is
  approached at bounded speed instead of in one jump.
- ``dt`` is derived from ``context.graph_time.real_time_ns`` and clamped to
  ``[min_dt, max_dt]``: a stalled or resumed pipeline (huge wall-clock gap) must
  not authorize a proportionally huge step, and a duplicate timestamp must not
  freeze the limiter. When no usable timestamp is available (both deltas zero or
  negative), ``nominal_dt`` is used.
- A dropped input frame holds the last emitted command (matching the upstream
  retargeters' hold-last convention) and does not advance the time baseline.
- A pipeline **reset** clears the baseline: the next valid frame passes through
  and re-latches (the owning task resets the arm pose; re-clamping against a
  stale pre-reset baseline would slew the arm across the workspace).
- **Anomaly rejection** (second tier, above the clamp): a frame whose *input*
  velocity relative to the last accepted input exceeds the ``reject_*``
  thresholds is a discontinuity -- an IK divergence, a tracking teleport, a
  stream catch-up step -- not motion to follow, and is **not executed at all**:
  the limiter holds the last emitted command instead of slewing toward the
  anomaly. After ``max_consecutive_rejections`` consecutive anomalous frames the
  input is treated as a persistent new target and re-accepted (still velocity
  clamped), so rejection cannot deadlock the pipeline; ``None`` holds
  indefinitely until the input returns within the envelope or a reset arrives.

The result is a three-band governor: normal motion passes through untouched,
modest overshoot is clamped to the velocity limit, and wild discontinuity is
refused outright. The clamp is intentionally a hard per-frame velocity bound (a
first-order rate limiter), not a smoothing filter: it adds no lag below the
limit -- teleop feel is untouched until the harness actually has to intervene.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    DLDataType,
    FloatType,
    NDArrayType,
)

# Output group key of the EE-pose limiter -- matches the upstream SO-101 clutch /
# Se3 retargeters so the limiter is a drop-in insertion in the pipeline wiring.
EE_POSE_KEY = "ee_pose"
# Output group key of the joint limiter -- matches JointStateRetargeter's
# ``joint`` mode output so the limiter is a drop-in insertion.
JOINT_TARGETS_KEY = "joint_targets"

# Numerical floor below which a quaternion norm is treated as degenerate and the
# previous orientation is held instead (never divide by ~zero; mirrors the
# defense-in-depth net in the SO-101 clutch retargeter).
_MIN_QUAT_NORM = 1e-6
# Angular steps below this [rad] pass through without axis extraction: the
# rotation axis is numerically meaningless near identity and the step is
# guaranteed under any sane limit.
_MIN_ANGLE_RAD = 1e-9


@dataclass
class RateLimiterConfig:
    """Configuration shared by the rate-limiting harness nodes.

    Args:
        max_linear_velocity: EE limiter only -- maximum linear speed [m/s] of the
            emitted position. The default is a deliberately conservative
            tabletop-arm bring-up value; raise it once the setup is trusted.
        max_angular_velocity: EE limiter only -- maximum angular speed [rad/s] of
            the emitted orientation (geodesic angle per second).
        max_joint_velocity: Joint limiter only -- default maximum per-joint speed
            [rad/s (revolute) or m/s (prismatic)] applied to every joint not
            overridden in ``joint_velocity_overrides``.
        joint_velocity_overrides: Joint limiter only -- per-joint ``{name: limit}``
            overrides of ``max_joint_velocity`` (e.g. a slower shoulder, a faster
            gripper).
        nominal_dt: Fallback frame period [s] used when the graph timestamps do
            not advance (first frame after a latch, duplicate timestamps).
        max_dt: Upper clamp [s] on the wall-clock frame delta. Bounds the step
            authorized after a pipeline stall/resume; a gap larger than this is
            treated as ``max_dt``.
        min_dt: Lower clamp [s] on the wall-clock frame delta, guarding against
            zero/near-zero deltas producing a frozen limiter.
        reject_linear_velocity: EE limiter only -- input linear speed [m/s]
            (measured against the last **accepted input**, over the clamped
            ``dt``) above which the frame is rejected outright instead of being
            approached at the clamp limit. ``None`` (default) disables
            rejection. Must be >= ``max_linear_velocity`` when set: a rejection
            threshold below the clamp limit would refuse motion the clamp band
            is meant to allow.
        reject_angular_velocity: EE limiter only -- input angular speed [rad/s]
            above which the frame is rejected outright. ``None`` disables.
            Must be >= ``max_angular_velocity`` when set.
        reject_joint_velocity: Joint limiter only -- per-joint input speed
            [rad/s or m/s] above which the whole frame is rejected outright
            (any single joint over the threshold rejects the frame -- joints
            move together; executing the sane joints of an insane frame still
            produces an insane configuration). ``None`` disables. Must be
            >= ``max_joint_velocity`` and every ``joint_velocity_overrides``
            entry when set.
        max_consecutive_rejections: Number of consecutive rejected frames after
            which the input is re-accepted as a persistent new target (then
            still approached at the clamp limits). Guards against a legitimate
            regime change (e.g. the leader really did move far during a stream
            outage) freezing the follower forever. ``None`` holds indefinitely;
            the default trips after ~1 s of anomalous input at 30 FPS.
    """

    max_linear_velocity: float = 0.25
    max_angular_velocity: float = 1.5
    max_joint_velocity: float = 1.5
    joint_velocity_overrides: dict[str, float] = field(default_factory=dict)
    nominal_dt: float = 1.0 / 60.0
    max_dt: float = 0.1
    min_dt: float = 1e-4
    reject_linear_velocity: float | None = None
    reject_angular_velocity: float | None = None
    reject_joint_velocity: float | None = None
    max_consecutive_rejections: int | None = 30

    def __post_init__(self) -> None:
        for field_name in (
            "max_linear_velocity",
            "max_angular_velocity",
            "max_joint_velocity",
            "nominal_dt",
            "max_dt",
            "min_dt",
        ):
            value = getattr(self, field_name)
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(f"{field_name} must be finite and > 0")
        for name, limit in self.joint_velocity_overrides.items():
            if not np.isfinite(limit) or limit <= 0.0:
                raise ValueError(
                    f"joint_velocity_overrides[{name!r}] must be finite and > 0"
                )
        if not self.min_dt <= self.nominal_dt <= self.max_dt:
            raise ValueError("require 0 < min_dt <= nominal_dt <= max_dt")
        for reject_name, clamp_name in (
            ("reject_linear_velocity", "max_linear_velocity"),
            ("reject_angular_velocity", "max_angular_velocity"),
            ("reject_joint_velocity", "max_joint_velocity"),
        ):
            reject = getattr(self, reject_name)
            if reject is None:
                continue
            if not np.isfinite(reject) or reject <= 0.0:
                raise ValueError(f"{reject_name} must be finite and > 0")
            if reject < getattr(self, clamp_name):
                raise ValueError(f"require {reject_name} >= {clamp_name}")
        if self.reject_joint_velocity is not None:
            for name, limit in self.joint_velocity_overrides.items():
                if self.reject_joint_velocity < limit:
                    raise ValueError(
                        "require reject_joint_velocity >= "
                        f"joint_velocity_overrides[{name!r}]"
                    )
        if self.max_consecutive_rejections is not None and (
            self.max_consecutive_rejections < 1
        ):
            raise ValueError("max_consecutive_rejections must be >= 1 or None")


def _clamped_dt(
    prev_ns: int | None, now_ns: int, nominal: float, lo: float, hi: float
) -> float:
    """Frame delta [s] from two ``real_time_ns`` stamps, clamped to ``[lo, hi]``.

    Falls back to ``nominal`` when there is no previous stamp or the clock did not
    advance (duplicate or non-monotonic timestamps).
    """
    if prev_ns is None:
        return nominal
    delta = (now_ns - prev_ns) * 1e-9
    if delta <= 0.0:
        return nominal
    return min(max(delta, lo), hi)


def _clamp_position_step(
    target: np.ndarray, previous: np.ndarray, max_step: float
) -> np.ndarray:
    """Clamp the Euclidean step from ``previous`` toward ``target`` to ``max_step`` [m].

    Returns ``target`` unchanged when it is within reach, else the point at
    ``max_step`` along the straight line from ``previous`` to ``target``.
    """
    delta = target - previous
    dist = float(np.linalg.norm(delta))
    if dist <= max_step or dist == 0.0:
        return target
    return previous + delta * (max_step / dist)


def _quat_normalize(q: np.ndarray) -> np.ndarray | None:
    """Return ``q`` normalized, or ``None`` when degenerate (zero / non-finite)."""
    norm = float(np.linalg.norm(q))
    if not np.isfinite(norm) or norm < _MIN_QUAT_NORM:
        return None
    return q / norm


def _quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product ``a (x) b`` of two ``[x, y, z, w]`` quaternions (scalar-last)."""
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


def _quat_conjugate(q: np.ndarray) -> np.ndarray:
    """Conjugate (== inverse for unit quaternions) of an ``[x, y, z, w]`` quaternion."""
    return np.array([-q[0], -q[1], -q[2], q[3]], dtype=np.float64)


def _quat_geodesic_angle(a: np.ndarray, b: np.ndarray) -> float:
    """Geodesic angle [rad] between two unit quaternions (double-cover aware)."""
    dot = min(1.0, abs(float(np.dot(a, b))))
    return 2.0 * float(np.arccos(dot))


def _clamp_orientation_step(
    target: np.ndarray, previous: np.ndarray, max_step: float
) -> np.ndarray:
    """Clamp the geodesic rotation from ``previous`` toward ``target`` to ``max_step`` [rad].

    Both quaternions are ``[x, y, z, w]`` unit quaternions. Returns ``target``
    (sign-aligned with the shortest arc) when the relative rotation is within
    ``max_step``, else the orientation reached by rotating ``max_step`` along the
    shortest arc from ``previous`` toward ``target``.
    """
    # Relative rotation in the previous frame's body frame: q_rel = prev^-1 (x) target.
    q_rel = _quat_mul(_quat_conjugate(previous), target)
    # Shortest arc: flip the double-cover sign so w >= 0.
    if q_rel[3] < 0.0:
        q_rel = -q_rel
    sin_half = float(np.linalg.norm(q_rel[:3]))
    angle = 2.0 * float(np.arctan2(sin_half, q_rel[3]))
    if angle <= max_step or angle < _MIN_ANGLE_RAD:
        # Within the limit: emit the target, but from the shortest-arc branch so
        # consecutive emitted quaternions never flip hemisphere spuriously.
        return _quat_mul(previous, q_rel)
    axis = q_rel[:3] / sin_half
    half = 0.5 * max_step
    q_step = np.array(
        [
            axis[0] * np.sin(half),
            axis[1] * np.sin(half),
            axis[2] * np.sin(half),
            np.cos(half),
        ],
        dtype=np.float64,
    )
    return _quat_mul(previous, q_step)


class EePoseRateLimiter(BaseRetargeter):
    """Bounds the per-frame linear/angular velocity of an absolute 7-D ``ee_pose`` stream.

    Input and output are both a single 7-D ``ee_pose`` (position [m] + orientation
    quaternion ``[x, y, z, w]``), the exact contract of ``SO101ClutchRetargeter`` /
    ``Se3AbsRetargeter``, so this node inserts between the pose producer and the
    downstream reorderer without any wiring changes.

    The first valid frame after construction / reset passes through and latches the
    baseline; each later frame is clamped to ``max_linear_velocity * dt`` [m] and
    ``max_angular_velocity * dt`` [rad] from the last **emitted** pose (see the
    module docstring for the dt and reset semantics).

    When ``reject_linear_velocity`` / ``reject_angular_velocity`` are set, a frame
    whose **input** moves faster than those thresholds relative to the last
    accepted input is rejected outright -- the last emitted pose is held and the
    anomalous target is never approached (see the module docstring's anomaly
    rejection tier).
    """

    def __init__(self, name: str, config: RateLimiterConfig | None = None) -> None:
        """Initialize the EE-pose rate limiter.

        Args:
            name: Name identifier for this retargeter node.
            config: Velocity limits and dt clamping; ``None`` uses the
                conservative :class:`RateLimiterConfig` defaults.
        """
        self._cfg = config if config is not None else RateLimiterConfig()
        super().__init__(name=name)
        self._last_pose: np.ndarray | None = None
        self._last_time_ns: int | None = None
        # Anomaly-rejection reference: the last *accepted* input (position +
        # normalized orientation), distinct from the last *emitted* pose -- the
        # emitted pose lags a far target by design, and measuring input velocity
        # against it would misread bounded catch-up as an anomaly.
        self._last_input_pos: np.ndarray | None = None
        self._last_input_ori: np.ndarray | None = None
        self._rejections: int = 0

    def input_spec(self) -> RetargeterIOType:
        """Requires an (optional) absolute 7-D ``ee_pose`` to govern."""
        return {
            EE_POSE_KEY: OptionalType(
                TensorGroupType(
                    EE_POSE_KEY,
                    [
                        NDArrayType(
                            "pose", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32
                        )
                    ],
                )
            )
        }

    def output_spec(self) -> RetargeterIOType:
        """Outputs the rate-limited absolute 7-D ``ee_pose``."""
        return {
            EE_POSE_KEY: TensorGroupType(
                EE_POSE_KEY,
                [
                    NDArrayType(
                        "pose", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32
                    )
                ],
            )
        }

    def _is_anomalous(self, pos: np.ndarray, ori: np.ndarray | None, dt: float) -> bool:
        """True when the input step from the last accepted input breaks the reject envelope."""
        cfg = self._cfg
        if (
            cfg.reject_linear_velocity is not None
            and self._last_input_pos is not None
            and float(np.linalg.norm(pos - self._last_input_pos))
            > cfg.reject_linear_velocity * dt
        ):
            return True
        return (
            cfg.reject_angular_velocity is not None
            and ori is not None
            and self._last_input_ori is not None
            and _quat_geodesic_angle(ori, self._last_input_ori)
            > cfg.reject_angular_velocity * dt
        )

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Emits the input pose clamped to the configured per-frame step."""
        if context.execution_events.reset:
            # Fresh episode: forget the baseline. The next valid frame passes
            # through and re-latches -- clamping against the stale pre-reset pose
            # would command a long cross-workspace slew.
            self._last_pose = None
            self._last_time_ns = None
            self._last_input_pos = None
            self._last_input_ori = None
            self._rejections = 0

        out = outputs[EE_POSE_KEY]
        inp = inputs[EE_POSE_KEY]
        if inp.is_none:
            # Dropped frame: hold the last emitted pose (upstream convention).
            # Keep the time baseline -- max_dt bounds the catch-up step anyway.
            if self._last_pose is not None:
                out[0] = self._last_pose.astype(np.float32)
            return

        pose = np.asarray(np.from_dlpack(inp[0]), dtype=np.float64)
        if not np.all(np.isfinite(pose[:3])):
            if self._last_pose is not None:
                out[0] = self._last_pose.astype(np.float32)
            return
        ori = _quat_normalize(pose[3:7])

        if self._last_pose is None:
            if ori is None:
                # Degenerate first orientation: nothing sane to latch; hold off.
                return
            # First valid frame: pass through, latch the baseline.
            latched = np.concatenate([pose[:3], ori])
            self._last_pose = latched
            self._last_time_ns = int(context.graph_time.real_time_ns)
            self._last_input_pos = pose[:3].copy()
            self._last_input_ori = ori.copy()
            self._rejections = 0
            out[0] = latched.astype(np.float32)
            return

        now_ns = int(context.graph_time.real_time_ns)
        dt = _clamped_dt(
            self._last_time_ns,
            now_ns,
            self._cfg.nominal_dt,
            self._cfg.min_dt,
            self._cfg.max_dt,
        )

        if self._is_anomalous(pose[:3], ori, dt):
            self._rejections += 1
            cap = self._cfg.max_consecutive_rejections
            if cap is None or self._rejections <= cap:
                # Anomalous frame (IK divergence, tracking teleport, stream
                # catch-up): refuse it entirely -- hold the last emitted pose
                # and advance no baseline (mirrors the dropped-frame path), so
                # the arm never starts moving toward a discontinuity.
                out[0] = self._last_pose.astype(np.float32)
                return
            # Cap tripped: the far input is persistent, so it is a new regime,
            # not a glitch. Fall through and re-accept it -- the clamp below
            # still bounds the approach velocity.
            self._rejections = 0
        else:
            self._rejections = 0

        pos = _clamp_position_step(
            pose[:3], self._last_pose[:3], self._cfg.max_linear_velocity * dt
        )
        if ori is None:
            # Degenerate target orientation: keep the last emitted one.
            ori_limited = self._last_pose[3:7]
        else:
            ori_limited = _clamp_orientation_step(
                ori, self._last_pose[3:7], self._cfg.max_angular_velocity * dt
            )

        self._last_input_pos = pose[:3].copy()
        if ori is not None:
            self._last_input_ori = ori.copy()
        limited = np.concatenate([pos, ori_limited])
        self._last_pose = limited
        self._last_time_ns = now_ns
        out[0] = limited.astype(np.float32)


class JointRateLimiter(BaseRetargeter):
    """Bounds the per-frame velocity of a name-keyed joint-target group.

    Input and output are both a ``joint_targets`` group with one ``FloatType`` per
    configured joint name, the exact contract of ``JointStateRetargeter``'s
    ``joint`` mode, so this node inserts between the leader mirror and the action
    wiring without changes. Every joint is clamped to ``limit * dt`` per frame,
    where ``limit`` is ``config.joint_velocity_overrides[name]`` when present,
    else ``config.max_joint_velocity``.

    The first valid frame after construction / reset passes through and latches the
    baseline (startup alignment is owned upstream); later frames are clamped
    against the last **emitted** targets (see the module docstring).

    When ``reject_joint_velocity`` is set, a frame in which **any** joint's input
    moves faster than that threshold relative to the last accepted input is
    rejected outright -- the last emitted targets are held and the anomalous
    frame is never approached (joints move together, so the whole frame is
    refused; see the module docstring's anomaly rejection tier).
    """

    def __init__(
        self,
        name: str,
        joint_names: list[str],
        config: RateLimiterConfig | None = None,
    ) -> None:
        """Initialize the joint-space rate limiter.

        Args:
            name: Name identifier for this retargeter node.
            joint_names: Ordered joint names; must match the upstream producer's
                output element names/order (checked by the graph at connect time).
            config: Velocity limits and dt clamping; ``None`` uses the
                conservative :class:`RateLimiterConfig` defaults.
        """
        if not joint_names:
            raise ValueError("joint_names must be non-empty")
        self._cfg = config if config is not None else RateLimiterConfig()
        self._joint_names = list(joint_names)
        unknown = set(self._cfg.joint_velocity_overrides) - set(self._joint_names)
        if unknown:
            raise ValueError(
                f"joint_velocity_overrides for unknown joints: {sorted(unknown)}"
            )
        super().__init__(name=name)
        self._limits = np.array(
            [
                self._cfg.joint_velocity_overrides.get(n, self._cfg.max_joint_velocity)
                for n in self._joint_names
            ],
            dtype=np.float64,
        )
        self._last_targets: np.ndarray | None = None
        self._last_time_ns: int | None = None
        # Anomaly-rejection reference: the last *accepted* input, distinct from
        # the last *emitted* targets (which lag a far target by design; measuring
        # input velocity against them would misread catch-up as an anomaly).
        self._last_input_targets: np.ndarray | None = None
        self._rejections: int = 0

    def input_spec(self) -> RetargeterIOType:
        """Requires an (optional) name-keyed joint-target group to govern."""
        return {
            JOINT_TARGETS_KEY: OptionalType(
                TensorGroupType(
                    JOINT_TARGETS_KEY, [FloatType(n) for n in self._joint_names]
                )
            )
        }

    def output_spec(self) -> RetargeterIOType:
        """Outputs the rate-limited joint targets, one ``FloatType`` per joint."""
        return {
            JOINT_TARGETS_KEY: TensorGroupType(
                JOINT_TARGETS_KEY, [FloatType(n) for n in self._joint_names]
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Emits the input targets clamped to the configured per-frame step."""
        if context.execution_events.reset:
            # Fresh episode: forget the baseline (see EePoseRateLimiter).
            self._last_targets = None
            self._last_time_ns = None
            self._last_input_targets = None
            self._rejections = 0

        out = outputs[JOINT_TARGETS_KEY]
        jin = inputs[JOINT_TARGETS_KEY]
        n = len(self._joint_names)
        if jin.is_none:
            # Dropped frame: hold the last emitted targets.
            if self._last_targets is not None:
                for i in range(n):
                    out[i] = float(self._last_targets[i])
            return

        targets = np.array([float(jin[i]) for i in range(n)], dtype=np.float64)
        if not np.all(np.isfinite(targets)):
            if self._last_targets is not None:
                for i in range(n):
                    out[i] = float(self._last_targets[i])
            return

        if self._last_targets is None:
            # First valid frame: pass through, latch the baseline.
            self._last_targets = targets
            self._last_time_ns = int(context.graph_time.real_time_ns)
            self._last_input_targets = targets.copy()
            self._rejections = 0
            for i in range(n):
                out[i] = float(targets[i])
            return

        now_ns = int(context.graph_time.real_time_ns)
        dt = _clamped_dt(
            self._last_time_ns,
            now_ns,
            self._cfg.nominal_dt,
            self._cfg.min_dt,
            self._cfg.max_dt,
        )

        if (
            self._cfg.reject_joint_velocity is not None
            and self._last_input_targets is not None
            and bool(
                np.any(
                    np.abs(targets - self._last_input_targets)
                    > self._cfg.reject_joint_velocity * dt
                )
            )
        ):
            self._rejections += 1
            cap = self._cfg.max_consecutive_rejections
            if cap is None or self._rejections <= cap:
                # Anomalous frame (e.g. IK output flipping tens of degrees in
                # one frame): refuse the whole frame -- hold the last emitted
                # targets and advance no baseline (mirrors the dropped-frame
                # path), so the servos never start slewing toward it.
                for i in range(n):
                    out[i] = float(self._last_targets[i])
                return
            # Cap tripped: the far input is persistent -- a new regime, not a
            # glitch. Fall through and re-accept it; the clamp below still
            # bounds the approach velocity.
            self._rejections = 0
        else:
            self._rejections = 0

        max_step = self._limits * dt
        delta = np.clip(targets - self._last_targets, -max_step, max_step)
        limited = self._last_targets + delta
        self._last_targets = limited
        self._last_time_ns = now_ns
        self._last_input_targets = targets.copy()
        for i in range(n):
            out[i] = float(limited[i])
