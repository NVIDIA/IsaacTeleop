# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Whether the operator's wrist is aligned enough for a clutch to latch.

Re-engaging a full-pose clutch rebases the arm onto wherever the hand is pointing, so this
makes alignment a precondition: it compares the controller's orientation against a
reference the caller supplies, and the caller feeds the answer to the clutch's
``ENGAGE_PERMITTED_INPUT``. An enable precondition, not a safety-rated stop -- the clutch
reads permission only where a latch is owed, so this can never drop a live engagement.

Not a graph node: three of its four operands are things the app already holds. Call
:meth:`EngageGate.update` once a frame instead.

``engaged`` is fed in rather than read because permission is ``engaged or verdict.ok``: the
clutch disarms during a tracking dropout and owes a latch on recovery, so a caller must
debounce its own engaged flag across brief dropouts, or get a re-alignment requirement on
every blink.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from .quaternion import MIN_QUAT_NORM, to_matrix

#: The clutch is already latched, so there is nothing to permit. Pure debounce: it holds
#: the verdict closed for the whole engagement, stopping a release re-latching in the dwell.
KEY_ENGAGED = "engaged"
#: No reference pose this frame -- the caller has nothing to align against yet.
KEY_UNREFERENCED = "unreferenced"
#: The controller is absent, flagged invalid, or carries no usable orientation.
KEY_UNTRACKED = "untracked"
#: The wrist is outside the alignment band.
KEY_ROTATION = "rotation"
#: Everything passes, but not yet for long enough.
KEY_SETTLING = "settling"
#: No frame has been judged yet, so a caller reading :attr:`EngageGate.verdict` early sees
#: "not yet" rather than "engageable".
KEY_UNJUDGED = "unjudged"

#: Rejects a scale, shear or reflection in the reference's rotation block -- O(0.1) errors,
#: not a precision policy. Matches ``SO101ClutchRetargeter``'s own orthonormality check.
_ORTHONORMAL_TOL = 1e-3


@dataclasses.dataclass(frozen=True)
class EngageGateConfig:
    """The band, the dwell, and how the frame delta is bounded.

    Only the relation between the two angles is pinned -- enter tighter than exit -- since
    no absolute value here is defensible without a headset on a real operator.
    """

    #: Below this the gate may open. Radians.
    enter_rad: float = math.radians(20.0)
    #: Above this an open gate closes again. Radians; must be >= :attr:`enter_rad`.
    exit_rad: float = math.radians(30.0)
    #: How long every conjunct must hold before the gate goes green. Seconds.
    dwell_s: float = 0.1
    #: Frame period assumed when the caller's clock does not advance. Seconds.
    nominal_dt: float = 1.0 / 60.0
    #: Upper clamp on the frame delta, so a stall cannot credit the dwell with the whole
    #: stall. Seconds.
    max_dt: float = 0.1

    def __post_init__(self) -> None:
        """Reject a configuration whose hysteresis is inverted or whose dwell is not a
        time."""
        if not 0.0 < self.enter_rad <= self.exit_rad:
            raise ValueError("require 0 < enter_rad <= exit_rad")
        if self.dwell_s < 0.0:
            raise ValueError("dwell_s must not be negative")
        if not 0.0 < self.nominal_dt <= self.max_dt:
            raise ValueError("require 0 < nominal_dt <= max_dt")


@dataclasses.dataclass(frozen=True)
class GateVerdict:
    """Whether the clutch may latch and -- when it may not -- why not.

    :attr:`failed` names every failing conjunct, not the first, so an operator is not told
    half the truth twice.
    """

    #: ``key`` is value-free, so a caller can drive a state transition off it; ``phrase``
    #: carries the measurement, for display.
    failed: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        """Whether every conjunct passed."""
        return not self.failed

    @property
    def keys(self) -> tuple[str, ...]:
        """The failing conjuncts' keys, in report order."""
        return tuple(key for key, _ in self.failed)

    @property
    def blocked(self) -> tuple[str, ...]:
        """The failing conjuncts' phrases, in report order."""
        return tuple(phrase for _, phrase in self.failed)


class EngageGate:
    """Gates a clutch's latch on wrist alignment, with hysteresis and a dwell.

    Drive it with :meth:`update` once per frame and read :attr:`permitted`, which is what
    the clutch's ``ENGAGE_PERMITTED_INPUT`` wants; :attr:`verdict` carries why. Stateful,
    so one instance belongs to one clutch and must not be shared.
    """

    def __init__(
        self,
        *,
        config: EngageGateConfig | None = None,
        app_conjunct: tuple[str, str] = ("app", "not ready"),
    ) -> None:
        """Initialize the gate, closed and with no dwell credit.

        Args:
            config: Band, dwell and dt bounds; ``None`` uses the defaults.
            app_conjunct: The ``(key, phrase)`` reported when :meth:`update` is given
                ``app_ok=False``. Naming it is the caller's job -- only the caller knows
                what its conjunct means.
        """
        self._config = config or EngageGateConfig()
        self._app_conjunct = (str(app_conjunct[0]), str(app_conjunct[1]))
        self._ok = False
        self._dwell_s = 0.0
        self._verdict = GateVerdict(((KEY_UNJUDGED, "no frame judged yet"),))
        self._permitted = False

    @property
    def verdict(self) -> GateVerdict:
        """The verdict computed on the last :meth:`update`. Before the first,
        :data:`KEY_UNJUDGED` -- never an empty verdict, which reads as "everything passed".
        """
        return self._verdict

    @property
    def permitted(self) -> bool:
        """What the clutch should be told: ``engaged or verdict.ok``, as of the last update."""
        return self._permitted

    def update(
        self,
        q_hand_xyzw: np.ndarray | None,
        reference_rotation: np.ndarray | None,
        *,
        engaged: bool,
        app_ok: bool = True,
        dt: float | None = None,
    ) -> GateVerdict:
        """Fold one frame in and return this frame's verdict.

        Args:
            q_hand_xyzw: The controller orientation to judge, ``[x, y, z, w]``, in the
                same frame as ``reference_rotation``. ``None`` for an untracked or
                invalid pose, which is reported rather than treated as aligned.
            reference_rotation: 3x3 rotation to align against, or a 4x4 whose rotation
                block is read. ``None`` means "nothing to align against yet".
            engaged: Is the clutch latched, as of the previous frame? See the module
                docstring on why this is fed in and on debouncing it.
            app_ok: One extra conjunct only the caller can evaluate. Fails **open**.
            dt: Seconds since the last update; ``None`` uses
                :attr:`EngageGateConfig.nominal_dt`. Clamped to ``max_dt``, so a stalled
                caller cannot credit the dwell with the whole stall.

        Returns:
            This frame's :class:`GateVerdict`, also available as :attr:`verdict`.
        """
        self._verdict = self._evaluate(
            q_hand_xyzw,
            reference_rotation,
            engaged=engaged,
            app_ok=app_ok,
            dt=self._bounded(dt),
        )
        self._permitted = bool(engaged or self._verdict.ok)
        return self._verdict

    # ------------------------------------------------------------------ internals

    def _bounded(self, dt: float | None) -> float:
        """The frame delta to credit the dwell with; ``nominal_dt`` for a missing or stalled one."""
        if dt is None or not math.isfinite(dt) or dt <= 0.0:
            return self._config.nominal_dt
        return min(float(dt), self._config.max_dt)

    def _evaluate(
        self,
        q_hand_xyzw: np.ndarray | None,
        reference_rotation: np.ndarray | None,
        *,
        engaged: bool,
        app_ok: bool,
        dt: float,
    ) -> GateVerdict:
        failed: list[tuple[str, str]] = []
        if engaged:
            failed.append((KEY_ENGAGED, "already engaged"))

        reference = _usable_rotation(reference_rotation)
        if reference is None:
            failed.append((KEY_UNREFERENCED, "no reference pose"))

        # No reach conjunct: a position residual would need a workspace envelope the gate
        # cannot know. The rotation conjunct is judged only where both operands exist, so
        # the verdict lists independent reasons.
        hand = _hand_rotation(q_hand_xyzw)
        if hand is None:
            failed.append((KEY_UNTRACKED, "controller not tracked"))
        elif reference is not None:
            theta = _geodesic_angle(reference, hand)
            tolerance = self._config.exit_rad if self._ok else self._config.enter_rad
            if not theta < tolerance:
                failed.append(
                    (
                        KEY_ROTATION,
                        f"rotation {math.degrees(theta):.0f} deg "
                        f"> {math.degrees(tolerance):.0f}",
                    )
                )

        if not app_ok:
            failed.append(self._app_conjunct)

        if failed:
            self._dwell_s = 0.0
            self._ok = False
            return GateVerdict(tuple(failed))

        self._dwell_s += dt
        if self._dwell_s < self._config.dwell_s:
            return GateVerdict(((KEY_SETTLING, "settling"),))
        self._ok = True
        return GateVerdict()


def _usable_rotation(rotation: np.ndarray | None) -> np.ndarray | None:
    """A reference's 3x3 rotation block, or None if it cannot be used.

    Takes a 3x3 or the rotation block of a 4x4. A sheared or scaled block yields a
    plausible, wrong angle, so it is refused rather than measured.
    """
    if rotation is None:
        return None
    matrix = np.asarray(rotation, dtype=np.float64)
    if matrix.shape not in ((3, 3), (4, 4)):
        raise ValueError(f"reference must be 3x3 or 4x4, got shape {matrix.shape}")
    block = matrix[:3, :3]
    if not np.all(np.isfinite(block)):
        return None
    residual = block.T @ block - np.eye(3)
    if float(np.max(np.abs(residual))) > _ORTHONORMAL_TOL:
        return None
    return block


def _hand_rotation(q_xyzw: np.ndarray | None) -> np.ndarray | None:
    """The controller's orientation as a 3x3, or None when the quaternion is unusable."""
    if q_xyzw is None:
        return None
    quat = np.asarray(q_xyzw, dtype=np.float64)
    norm = float(np.linalg.norm(quat))
    if not np.isfinite(norm) or norm < MIN_QUAT_NORM:
        return None
    # to_matrix is wxyz; reorder field by field, never sliced.
    q = quat / norm
    return to_matrix(np.array([q[3], q[0], q[1], q[2]]))


def _geodesic_angle(a: np.ndarray, b: np.ndarray) -> float:
    """Angle [rad] of the rotation carrying ``a`` onto ``b``, in ``[0, pi]``.

    From the relative matrix's trace, which is blind to the double cover and spares a
    matrix-to-quaternion conversion of the reference.
    """
    cosine = (float(np.trace(a.T @ b)) - 1.0) / 2.0
    return float(np.arccos(min(1.0, max(-1.0, cosine))))
