# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Engage-relative full-pose clutch retargeter for the SO-101 5-DOF arm.

Clutches the **full pose**: on every engage it re-latches *both* the home position and the home
orientation, so the operator can disengage, reposition their hand, and re-engage without the arm
moving. Each engaged frame emits::

    pos = home_pos + position_scale * (grip_pos - origin_pos)   # scaled translation
    rot = (R_ctrl @ R_origin^-1) @ R_home                       # base-frame delta, 1:1

On the engage frame ``grip_pos == origin_pos`` and ``R_ctrl == R_origin``, so the output is
*exactly* the home pose whatever the scale -- no teleport. Because the orientation delta is
**left**-composed (base frame), a hand rotation about base Z maps to an EE rotation about base Z.

Engagement is ``execution_state == RUNNING`` **and** ``squeeze > squeeze_threshold``. The two
conjuncts are different things and both are load-bearing: ``squeeze`` is *operator intent*, while
``execution_state`` is *system readiness*. An owning application that is still homing the arm
holds ``STOPPED`` so a squeeze cannot latch a home the arm has not reached yet.

Latching uses a **pending-latch sentinel**: ``_origin is None`` means "a latch is owed". The
sentinel is cleared (re-armed) on every disengaged, dropped, invalid or degenerate frame, so the
latch stays owed until a frame arrives that can be trusted to latch off. Both halves are
necessary -- arm-then-fire *without* the re-arm silently jumps when the operator releases and
re-squeezes across a tracking dropout, because the squeeze is unobservable inside the gap.

Home latching is deliberately **asymmetric**:

* the home **position** comes from the arm's measured EE pose when
  :data:`MEASURED_BASE_T_EE_INPUT` is connected, so an arm that sagged or was pushed while
  disengaged is not snapped back to a stale command;
* the home **orientation** is *always* the last commanded rotation, never the measurement. The
  5-DOF SO-101 tracks orientation only softly, so its measured wrist orientation persistently
  differs from the command; latching the measurement would inject that offset into the commanded
  signal on **every** re-clutch. Position has no such tracking gap.

On ``execution_events.reset`` the held pose is re-seeded from the **configured** home -- the
transform most recently supplied to the constructor or to :meth:`set_home_base_T_ee` -- and the
latch is re-armed. Seeding from a *static configured* transform rather than from live arm state is
what makes this safe: the reset pulse can reach this retargeter on either side of the owner's
actual teleport, so anything read from the arm at reset time is stale on one of those orderings.
The owning task is expected to slew the arm to that same configured pose on reset (Isaac Lab's
``init_state`` does exactly that), which is what makes the re-seed jump-free. An owner whose reset
does *not* move the arm should keep the configured home up to date with
:meth:`set_home_base_T_ee`, or simply not fire ``reset``.

That "never from live arm state" scopes to the **re-seed**, not to the whole frame. A frame that
carries ``reset`` can also latch the clutch, and the latch is unchanged by the re-seed having just
happened: the normal engage rule still applies, so on such a frame the home **position** comes from
:data:`MEASURED_BASE_T_EE_INPUT` when it is connected, not from the re-seed. Note that this does
not escape the ordering problem above -- ``GRIP_IS_VALID`` and the squeeze qualify the *controller*
pose, and say nothing about whether the arm has been teleported yet, so on a reset-before-teleport
ordering that measurement is the previous episode's arm state. No consumer wires both today. One
that does should either not fire ``reset`` on a frame it also engages, or leave the measured input
unwired. The re-seed's own job is unaffected: it defines what the retargeter holds, and re-latches
*from*, when nothing engages.

.. note::
   There is deliberately **no** ``orientation_offset`` parameter. It is not merely unnecessary
   here, it is *wrong*: appending a fixed offset gives ``(R_ctrl . R_origin^-1 . R_home) . R_off``,
   and on the engage frame ``R_ctrl == R_origin``, so the output is ``R_home . R_off != R_home`` --
   which breaks the no-teleport invariant. Worse, because ``_home_rot`` re-latches from the last
   *commanded* rotation, the error compounds as ``R_off``, ``R_off^2``, ``R_off^3`` over successive
   re-clutches. Do not re-add it.

.. note::
   Orientation **wind-up** is a real property of this algebra and is intentionally preserved: the
   commanded rotation is unbounded in SO(3) across repeated re-clutches, and ``wrist_roll`` sits in
   the null space of the 5-DOF position objective. Mitigating it would change behaviour.

Quaternion helpers are inlined below rather than imported: the equivalents in
``retargeting_engine/python/utilities/transform_utils.py`` (``_rotation_matrix_to_quat_xyzw`` at
``:116``, ``_quat_multiply_xyzw`` at ``:158``) are private to the engine layer. No SciPy either,
so this retargeter needs nothing beyond NumPy at install time.
"""

from __future__ import annotations

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
    DLDataType,
    NDArrayType,
    TransformMatrix,
)

# Identity orientation quaternion [x, y, z, w].
_IDENTITY_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
# Element index of the 4x4 matrix inside a ``TransformMatrix()`` tensor group.
_MATRIX_INDEX = 0
# Minimum norm below which an incoming grip quaternion is treated as degenerate. The
# ``GRIP_IS_VALID`` gate is the primary guard against untracked poses; this is the secondary
# "never divide by zero" net for a source that flags the pose valid yet emits a zero /
# non-finite quaternion (normalizing which would feed NaN into the downstream SE3 IK).
_MIN_QUAT_NORM = 1e-6
# Absolute tolerance for the ``home_base_T_ee`` rotation-block orthonormality check. This check
# exists to reject a *scale, shear or reflection*, which are O(0.1) errors or worse; it is
# emphatically NOT a precision policy, so the tolerance is set generously.
#
# Measured worst cases over 2000 random SO(3) samples: a rotation round-tripped through float32
# lands at 8.1e-08 (callers routinely build the transform as a float32 matrix, and
# ``TransformMatrix`` is float32 by tensor type), and a float32 quaternion converted to a matrix --
# the path a caller takes when reading a measured EE orientation off a sensor -- reaches 4.5e-07.
# A matrix hand-typed from rounded decimal literals is coarser still, and coarse enough to matter:
# over 20000 random SO(3), rounding to **4** decimals reaches ``max|R.T @ R - I| == 1.6e-4`` and so
# is rejected ~16% of the time, whereas **5** decimals peaks at 1.6e-5 and is never rejected. Hence
# 1e-4, and hence: type at least 5 decimals. Against that, 1e-4 leaves room for every legitimate
# input while the smallest defect worth catching (a 0.2 shear) fails by 2000x.
_ROTATION_ATOL = 1e-4


def _normalize_quat(q: np.ndarray) -> np.ndarray:
    """Return ``q`` scaled to unit norm (``[x, y, z, w]``); a zero quaternion is returned as-is.

    Every composition step normalizes, mirroring the reference implementation this retargeter
    reproduces, whose rotation type normalizes on construction.
    """
    norm = float(np.linalg.norm(q))
    return q / norm if norm > 0.0 else q


def _quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product ``a (x) b`` of two ``[x, y, z, w]`` quaternions (scalar-last).

    Verbatim equivalent of ``transform_utils._quat_multiply_xyzw`` (``:158``), inlined to avoid
    depending on an engine-private helper from the retargeter layer. Follows the SciPy
    ``Rotation`` composition convention: ``(Ra * Rb).as_quat() == _quat_mul(Ra.as_quat(),
    Rb.as_quat())``.
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


def _quat_inv(q: np.ndarray) -> np.ndarray:
    """Inverse of an ``[x, y, z, w]`` quaternion: normalize, then conjugate.

    The conjugate is the inverse only for a *unit* quaternion, hence the normalize first. This
    matches the reference implementation, whose ``inv()`` conjugates a value its constructor has
    already normalized.
    """
    x, y, z, w = _normalize_quat(q)
    return np.array([-x, -y, -z, w], dtype=np.float64)


def _mat_to_quat_xyzw(matrix: np.ndarray) -> np.ndarray:
    """Convert a 3x3 rotation matrix to a unit ``[x, y, z, w]`` quaternion (Shepperd's method).

    Verbatim equivalent of ``transform_utils._rotation_matrix_to_quat_xyzw`` (``:116``), inlined
    for the same reason as :func:`_quat_mul`, **plus a normalize** of the result that the engine
    copy omits -- everything downstream of the home latch assumes unit quaternions.

    Branch-on-trace conversions are not eyeball-verifiable, so this is pinned numerically against
    an independent reference over random SO(3) in
    ``retargeting_engine_tests/python/test_so101_retargeters.py``.
    """
    m00, m01, m02 = matrix[0, 0], matrix[0, 1], matrix[0, 2]
    m10, m11, m12 = matrix[1, 0], matrix[1, 1], matrix[1, 2]
    m20, m21, m22 = matrix[2, 0], matrix[2, 1], matrix[2, 2]
    trace = m00 + m11 + m22

    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (m21 - m12) * s
        y = (m02 - m20) * s
        z = (m10 - m01) * s
    elif m00 > m11 and m00 > m22:
        s = 2.0 * np.sqrt(1.0 + m00 - m11 - m22)
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = 2.0 * np.sqrt(1.0 + m11 - m00 - m22)
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = 2.0 * np.sqrt(1.0 + m22 - m00 - m11)
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s

    return _normalize_quat(np.array([x, y, z, w], dtype=np.float64))


class SO101ClutchRetargeter(BaseRetargeter):
    """Clutch-rebases an XR controller onto an absolute SO-101 EE pose, re-latching every engage.

    Emits an absolute 7D ``ee_pose`` (position ``[x, y, z]`` [m] + orientation quaternion
    ``[x, y, z, w]``) with the exact same output contract as
    :class:`~isaacteleop.retargeters.Se3AbsRetargeter` (node ``name="ee_pose"``, output key
    ``"ee_pose"``, ``NDArrayType("pose", shape=(7,))``), so a downstream reorderer is unaffected.

    Frame contract: the controller stream reaching this retargeter must already be expressed in the
    robot **base** frame (rebase it upstream, e.g. via ``ControllersSource.transformed``). The
    engage-relative delta is applied directly, with no world->base rotation of its own. Under an
    upstream rigid rebase ``p -> R @ p + t``, the rebase's translation ``t`` cancels exactly in
    ``grip_pos - origin_pos``. Its rotation ``R`` does not: it **rotates the translation delta**
    and conjugates the orientation delta, so a wrong rebase rotation mis-maps *both* channels --
    a hand push along +X can come out as EE motion along +Y.

    .. warning::
       The upstream rebase is a **static configuration** encoding an assumption about where the
       operator's XR anchor sits relative to the robot base. Nothing here can validate it: this
       retargeter's own correctness says nothing about whether that frame is right, and a wrong
       rebase rotation shows up as an intuitive-but-wrong hand-to-EE mapping, not as an error.

    Inputs:
        - ``input_device`` -- Optional :func:`ControllerInput` grip pose, validity and squeeze.
        - :data:`MEASURED_BASE_T_EE_INPUT` -- Optional ``base_T_ee`` 4x4 transform of the arm's
          *measured* EE pose. Only its translation block is read, and only on the engage frame.
          When absent, the home position falls back to the last commanded position.

    Outputs:
        - ``ee_pose`` -- a single 7D ``[x, y, z, qx, qy, qz, qw]`` float32 ``NDArray``.

    Reset: ``execution_events.reset`` re-seeds the held pose from the configured home and re-arms
    the latch -- see :meth:`set_home_base_T_ee` and the module docstring. Nothing else in the
    frame path is stateful, so that is the whole of the reset contract.

    See the module docstring for the algebra, the asymmetric home latch, and why there is no
    ``orientation_offset``.
    """

    #: Input key for the arm's measured ``base_T_ee`` pose, used to latch the home position. The
    #: symbol names the frame because the frame is the whole point:
    #: deliberately **not** ``JointStateRetargeter.ROBOT_EE_POS_INPUT``, which carries a
    #: ``world_T_ee`` while this is a ``base_T_ee``. Same tensor type, different frame -- so a
    #: mis-wire would be a silently wrong home with no type error to catch it. Producers should
    #: reference this attribute rather than re-declaring the string.
    #:
    #: The input is ``OptionalType``, and a consumer **may omit it entirely** from
    #: :meth:`~isaacteleop.retargeting_engine.interface.BaseRetargeter.connect` -- optional inputs
    #: are exempt from the missing-input check (``base_retargeter.py:213``). A consumer whose owning
    #: task slews the arm to a known configured home (Isaac Lab) legitimately leaves it unwired and
    #: rides the last-commanded fallback.
    #:
    #: What ``OptionalType`` does **not** buy is the right to skip a key you *did* wire. If this
    #: input is connected to a ``ValueInput`` leaf, that leaf is an external graph input, and
    #: ``TeleopSession`` validates every external leaf name is present in ``external_inputs`` on
    #: every step, independently of ``OptionalType``. Such a producer must send the key
    #: unconditionally, carrying an absent ``OptionalTensorGroup`` on frames with no pose.
    MEASURED_BASE_T_EE_INPUT = "measured_base_T_ee"

    def __init__(
        self,
        name: str,
        home_base_T_ee: np.ndarray,  # noqa: N803
        *,
        input_device: str = ControllersSource.RIGHT,
        position_scale: float = 1.0,
        squeeze_threshold: float = 0.5,
    ) -> None:
        """Initialize the clutch retargeter.

        Args:
            name: Name identifier for this retargeter node.
            home_base_T_ee: Required ``base_T_ee`` 4x4 transform [m] giving the EE pose in the
                robot base frame that seeds the held pose. **Both** blocks are used: the
                translation seeds the home position, the rotation seeds the home orientation. Pass
                the arm's measured startup pose so the first engage is jump-free. It is also the
                pose a ``reset`` re-seeds to. When the pose is not known until after construction
                (e.g. the graph is built before the arm is homed), pass a placeholder and call
                :meth:`set_home_base_T_ee` before the first ``RUNNING`` frame.
            input_device: Controller source key to read the grip pose from.
            position_scale: Dimensionless controller-to-EE translation gain applied to the
                engage-relative delta. ``1.0`` is 1:1 motion; a value ``< 1`` shrinks robot travel
                relative to hand travel, which is what lets a comfortable operator arm sweep
                (~0.7 m) stay inside the SO-101's ~0.35 m reach. Applies to **translation only** --
                the orientation delta is always 1:1, since a scaled rotation is disorienting and
                the 5-DOF wrist tracks orientation softly anyway. Must be positive and finite:
                ``0`` freezes the EE, a negative value inverts the hand->EE mapping, and the finite
                check closes the ``inf * 0 = nan`` path before it reaches the IK.
            squeeze_threshold: Squeeze value above which the clutch is engaged, combined by AND
                with ``execution_state == RUNNING``. This is the **only** place the threshold is
                compared; owning loops should read :attr:`is_engaged` rather than re-deriving it.
                Must be finite and in ``[0, 1)``: the squeeze axis is normalized to ``[0, 1]``, so
                a threshold of ``1.0`` or above can never be exceeded and ``NaN`` makes every
                comparison False -- either way the clutch would silently never engage.

        Raises:
            ValueError: If ``position_scale`` is not positive and finite, if
                ``squeeze_threshold`` is not finite or lies outside ``[0, 1)``, or if
                ``home_base_T_ee`` is not a 4x4 transform with an orthonormal rotation block.
        """
        self._input_device = input_device

        position_scale = float(position_scale)
        if not np.isfinite(position_scale) or position_scale <= 0.0:
            raise ValueError(
                f"position_scale must be positive and finite, got: {position_scale!r}"
            )
        self._position_scale = position_scale

        squeeze_threshold = float(squeeze_threshold)
        if not np.isfinite(squeeze_threshold) or not (0.0 <= squeeze_threshold < 1.0):
            raise ValueError(
                "squeeze_threshold must be finite and in [0, 1), got: "
                f"{squeeze_threshold!r}"
            )
        self._squeeze_threshold = squeeze_threshold

        # All clutch state is float64. The float32 ``_last_pose`` below is a write-only mirror for
        # emission: it is NEVER read back into state. Reading the running home out of the float32
        # output would quantize both channels on every re-clutch. The two channels differ in how
        # much that matters: the home POSITION is re-seeded from the measured input on most
        # engages (and that input is float32 by tensor type anyway, so its own resolution is the
        # floor), but the home ORIENTATION is always taken from the last commanded rotation and
        # has no measured re-seed path at all -- so there the error genuinely compounds across
        # re-clutches, without bound.
        self._last_commanded_pos = np.zeros(3, dtype=np.float64)
        self._last_commanded_rot = _IDENTITY_QUAT.copy()
        self._home_pos = np.zeros(3, dtype=np.float64)
        self._home_rot = _IDENTITY_QUAT.copy()
        # Latched controller origin, and the pending-latch sentinel: ``None`` means "a latch is
        # owed on the next usable engaged frame". Set ONLY by the latch, cleared by every disarm --
        # which is what makes :attr:`is_engaged` exactly track the latch.
        self._origin: np.ndarray | None = None
        self._origin_rot = _IDENTITY_QUAT.copy()
        self._last_pose = np.zeros(7, dtype=np.float32)
        # The configured home a ``reset`` re-seeds to; owned by set_home_base_T_ee.
        self._configured_home = np.eye(4, dtype=np.float64)
        self.set_home_base_T_ee(home_base_T_ee)

        # LAST: BaseRetargeter.__init__ calls input_spec(), which reads self._input_device.
        super().__init__(name=name)

    # ------------------------------------------------------------------ state

    def set_home_base_T_ee(self, home_base_T_ee: np.ndarray) -> None:  # noqa: N803
        """Re-seed the held pose from a ``base_T_ee`` 4x4 transform.

        For owners that cannot know the arm's pose at construction time (the retargeting graph is
        built before the arm is homed). Both blocks are used, exactly as in the constructor. The
        supplied transform also becomes the **configured home** that a subsequent ``reset``
        re-seeds to, so an owner that re-homes its arm mid-session should call this rather than
        letting reset drag the arm back to the construction-time pose.

        Call this only while the clutch is not engaged -- typically while the session holds
        ``STOPPED``, which makes latching impossible and so makes the ordering unambiguous: the new
        home takes effect before the first ``RUNNING`` frame.

        The pending latch is re-armed as a safety net rather than the call being rejected. Without
        it, a call made while engaged would leave the *old* controller origin latched against the
        *new* home, and the very next frame would command
        ``new_home + scale * (grip_pos - old_origin)`` -- a jump of ``new_home - old_home`` at
        servo speed. Re-arming bounds that: the next engaged frame re-latches rather than applying
        a stale delta. It does **not** make the call free. The re-latch still homes on whatever
        this call supplied, so the commanded pose still steps to the new home -- measured at
        0.0100 m with the measured-EE input connected versus 1.3398 m without it on the same
        sequence -- and the ORIENTATION snaps to the new home rotation either way, since it has no
        measured rescue path at all (90.00 deg in a single frame, measured). Raising would still
        be worse: this sits one call away from a frame-rate loop, where turning a jump into an
        unhandled exception leaves the arm uncommanded. Call it while disengaged.

        That is not in tension with the ``ValueError``\\ s below, which draw the line elsewhere: a
        **malformed argument** raises, because there is no pose to command from it and continuing
        would only defer the same failure to a wrong orientation nobody can trace. **Bad timing**
        never raises -- the transform is well-formed, the retargeter can keep commanding, and the
        cost is a bounded jump rather than an uncommanded arm.

        Args:
            home_base_T_ee: ``base_T_ee`` 4x4 transform [m]; its rotation block must be a proper
                rotation (orthonormal, ``det == +1``) and its bottom row ``[0, 0, 0, 1]``.

        Raises:
            ValueError: If the transform is not 4x4, is not finite, has a bottom row other than
                ``[0, 0, 0, 1]``, or its rotation block is not a proper rotation. A scaled or
                reflected block would still normalize to a unit quaternion and command a quietly
                *wrong* orientation, with nothing downstream to catch it; the bottom-row check
                additionally catches a **transposed** transform, which is otherwise indistinguishable
                from a valid one. None of this can catch an inverted transform -- an ``ee_T_base``
                passed here is a perfectly well-formed 4x4 and is accepted.
        """
        home = np.asarray(home_base_T_ee, dtype=np.float64)
        if home.shape != (4, 4):
            raise ValueError(
                f"home_base_T_ee must be a 4x4 transform, got shape {home.shape}"
            )
        rot = home[:3, :3]
        if not np.all(np.isfinite(home)):
            raise ValueError("home_base_T_ee must be finite")
        # Bottom row, checked before the rotation block so the message names the real fault. This
        # is what catches a TRANSPOSED transform, which every other check here waves through: the
        # rotation block of ``base_T_ee.T`` is ``R.T``, still orthonormal with ``det == +1``, and
        # the translation ends up in the bottom row, leaving column 3 zeroed -- so the clutch would
        # silently home at the base origin with the inverse orientation.
        if not np.allclose(home[3], [0.0, 0.0, 0.0, 1.0], atol=_ROTATION_ATOL):
            raise ValueError(
                "home_base_T_ee bottom row must be [0, 0, 0, 1] (a transposed transform is the "
                f"usual cause); got: {home[3]}"
            )
        if not np.allclose(rot.T @ rot, np.eye(3), atol=_ROTATION_ATOL):
            raise ValueError(
                "home_base_T_ee rotation block must be orthonormal (R.T @ R == I within "
                f"{_ROTATION_ATOL}); got:\n{rot}"
            )
        det = float(np.linalg.det(rot))
        if abs(det - 1.0) > _ROTATION_ATOL:
            raise ValueError(
                "home_base_T_ee rotation block must be a proper rotation (det == +1 within "
                f"{_ROTATION_ATOL}); got det == {det!r}"
            )
        # Store the configured home FIRST, and as a copy: the reset path calls this method with
        # ``self._configured_home`` itself, so reading from an aliased buffer would be a trap.
        self._configured_home = home.copy()
        self._last_commanded_pos = home[:3, 3].copy()
        self._last_commanded_rot = _mat_to_quat_xyzw(rot)
        self._home_pos = self._last_commanded_pos.copy()
        self._home_rot = self._last_commanded_rot.copy()
        self._last_pose = np.concatenate(
            [self._last_commanded_pos, self._last_commanded_rot]
        ).astype(np.float32)
        # Re-arm: never leave a stale origin latched against a fresh home. Idempotent on the
        # constructor path, where the sentinel is already None. MUST stay last -- the reset path
        # relies on this call re-arming the latch as its final act.
        self._origin = None

    @property
    def is_engaged(self) -> bool:
        """Whether the clutch was engaged and tracking on the **last computed frame**.

        Exactly ``self._origin is not None``, so its rising edge *is* the latch frame: the sentinel
        is set only by the latch and cleared by every disarm. An owning loop can therefore derive
        the engage edge as ``is_engaged and not prev_is_engaged`` without re-deriving engagement
        from ``squeeze`` -- which it could not do correctly anyway, since the latch can be deferred
        by an unusable frame or a stale session frame that the loop cannot observe.

        Only meaningful after a ``compute()``; ``False`` before the first one. Anything that
        changes engagement -- a squeeze, an ``execution_state`` change, a re-seeded home -- takes
        effect on the **next** ``compute()``, not at the moment it happens.
        """
        return self._origin is not None

    # ------------------------------------------------------------------ specs

    def input_spec(self) -> RetargeterIOType:
        """Controller grip pose (base frame) plus the optional measured EE pose for the home."""
        return {
            self._input_device: OptionalType(ControllerInput()),
            self.MEASURED_BASE_T_EE_INPUT: OptionalType(TransformMatrix()),
        }

    def output_spec(self) -> RetargeterIOType:
        """Outputs an absolute 7D ee pose (position [m] + quaternion [x, y, z, w])."""
        return {
            "ee_pose": TensorGroupType(
                "ee_pose",
                [
                    NDArrayType(
                        "pose", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32
                    )
                ],
            )
        }

    # ---------------------------------------------------------------- compute

    def _latch(
        self, inputs: RetargeterIO, grip_pos: np.ndarray, grip_rot: np.ndarray
    ) -> None:
        """Latch the engage home (where the arm is now) and the controller origin."""
        measured = inputs.get(self.MEASURED_BASE_T_EE_INPUT)
        if measured is not None and not measured.is_none:
            base_T_ee = np.from_dlpack(measured[_MATRIX_INDEX]).astype(np.float64)  # noqa: N806
            self._home_pos = base_T_ee[:3, 3].copy()
        else:
            # Documented fallback, and the *designed* path for a consumer that leaves
            # MEASURED_BASE_T_EE_INPUT unwired because its owning task slews the arm to a known
            # configured home on reset. Not degraded mode, so it is deliberately silent.
            self._home_pos = self._last_commanded_pos.copy()
        # ALWAYS the last commanded rotation, never the measurement -- see the module docstring.
        self._home_rot = self._last_commanded_rot.copy()
        self._origin = grip_pos.copy()
        self._origin_rot = _normalize_quat(grip_rot)

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Computes the engage-relative clutch pose; holds the last commanded pose otherwise."""
        ee_pose = outputs["ee_pose"]

        if context.execution_events.reset:
            # Re-seed the held pose from the CONFIGURED home and re-arm the latch (the re-arm is
            # set_home_base_T_ee's last act). The seed is a static configured transform, never live
            # arm state: the reset pulse can reach this retargeter on either side of the owner's
            # actual teleport, so anything read from the arm at reset time is stale on one of those
            # orderings. Re-seeding also refreshes the held pose, so the value emitted on a
            # disengaged frame after a reset matches the physically-homed arm instead of leaking
            # the previous episode's last commanded pose.
            self.set_home_base_T_ee(self._configured_home)

        running = context.execution_events.execution_state == ExecutionState.RUNNING
        inp = inputs[self._input_device]

        if inp.is_none:
            # Dropped frame: hold, and re-arm so the latch stays owed. Re-arming matters because
            # the squeeze is unobservable across the gap -- if the operator released and
            # re-squeezed inside it, keeping the old origin would rebase against a stale engagement
            # and jump the arm by the whole accumulated hand motion.
            self._origin = None
            ee_pose[0] = self._last_pose
            return

        if not bool(inp[ControllerInputIndex.GRIP_IS_VALID]):
            # Controller present but its grip pose is not localizable this frame (the OpenXR
            # XR_SPACE_LOCATION_*_VALID_BITs are clear), so the source passes through an untrusted
            # pose. Treat it like a dropped frame and never latch the clutch origin off it.
            self._origin = None
            ee_pose[0] = self._last_pose
            return

        grip_pos = np.from_dlpack(inp[ControllerInputIndex.GRIP_POSITION]).astype(
            np.float64
        )
        grip_rot = np.from_dlpack(inp[ControllerInputIndex.GRIP_ORIENTATION]).astype(
            np.float64
        )  # XYZW
        squeeze = float(inp[ControllerInputIndex.SQUEEZE_VALUE])

        grip_norm = float(np.linalg.norm(grip_rot))
        if (
            not np.all(np.isfinite(grip_pos))
            or not np.isfinite(grip_norm)
            or grip_norm < _MIN_QUAT_NORM
        ):
            # Defense in depth behind GRIP_IS_VALID, on BOTH channels of the same ``XrPosef``. A
            # degenerate quaternion cannot produce a meaningful orientation delta, and a non-finite
            # position would propagate into the commanded pose -- from where it never recovers,
            # because the held pose and the last-commanded home fallback are then NaN too, and NaN
            # comparisons are False so no downstream bounds check rejects it.
            self._origin = None
            ee_pose[0] = self._last_pose
            return

        if not (running and squeeze > self._squeeze_threshold):
            # Disengaged: hold the last commanded pose and re-arm.
            self._origin = None
            ee_pose[0] = self._last_pose
            return

        if self._origin is None:
            self._latch(inputs, grip_pos, grip_rot)

        pos = self._home_pos + self._position_scale * (grip_pos - self._origin)
        # Left-composed (base frame): (R_ctrl . R_origin^-1) . R_home. Operand order is
        # load-bearing -- the plausible wrong orderings diverge by O(1), not by a rounding.
        rot = _normalize_quat(
            _quat_mul(_normalize_quat(grip_rot), _quat_inv(self._origin_rot))
        )
        rot = _normalize_quat(_quat_mul(rot, self._home_rot))

        self._last_commanded_pos = pos
        self._last_commanded_rot = rot
        self._last_pose = np.concatenate([pos, rot]).astype(np.float32)
        ee_pose[0] = self._last_pose
