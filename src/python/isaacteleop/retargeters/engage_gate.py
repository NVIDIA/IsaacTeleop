# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Whether the operator's wrist is aligned enough for a clutch to latch.

Re-engaging a full-pose clutch rebases the arm onto wherever the hand happens to be
pointing, so a latch taken at an arbitrary wrist angle winds the commanded orientation
somewhere the operator did not ask for. This node makes the alignment a precondition:
it compares the controller's orientation against a reference the owner supplies, and
emits into
:data:`~isaacteleop.retargeters.SO101.clutch_retargeter.SO101ClutchRetargeter.ENGAGE_PERMITTED_INPUT`.

**An enable precondition, not a safety-rated stop.** The clutch reads permission only
where a latch is owed, so this can never drop a live engagement -- see the clutch's own
docstring for what that costs and buys.

The graph is a pull-based DAG, so the node cannot read the clutch it feeds. What the
owner must hand back instead is one bool on :data:`EngageAlignmentGate.ENGAGED_INPUT`:
whether the clutch is latched, as of the previous frame. Permission is then
``engaged or verdict.ok``, and that disjunction is load-bearing rather than cosmetic --
during a tracking dropout the clutch disarms and owes a latch on recovery, and a gate
answering "not aligned" there would stop the arm mid-engagement. An owner that debounces
its own engaged flag across brief dropouts (holding it True through the gap) is what
makes recovery jump-free; an owner that forwards the raw flag gets a re-alignment
requirement on every blink.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import BaseRetargeter, RetargeterIOType
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tensor_group_type import OptionalType
from isaacteleop.retargeting_engine.tensor_types import (
    BoolFlag,
    ControllerInput,
    EngagePermission,
    HandPose,
    TransformMatrix,
)
from isaacteleop.retargeting_engine.utilities.transform_utils import (
    quat_xyzw_to_rotation_matrix,
)

#: The clutch is already latched, so there is nothing to permit. Pure debounce: it holds
#: the verdict closed for the whole engagement, which is what stops a release from
#: re-latching inside the dwell.
KEY_ENGAGED = "engaged"
#: No reference pose this frame -- the owner has nothing to align against yet.
KEY_UNREFERENCED = "unreferenced"
#: The controller is absent, flagged invalid, or carries no usable orientation.
KEY_UNTRACKED = "untracked"
#: The wrist is outside the alignment band.
KEY_ROTATION = "rotation"
#: Everything passes, but not yet for long enough.
KEY_SETTLING = "settling"
#: No frame has been judged yet. What :attr:`EngageAlignmentGate.verdict` reports before
#: the first step, so a caller reading it early sees "not yet" rather than "engageable".
KEY_UNJUDGED = "unjudged"

#: Element index of the 4x4 matrix inside a :func:`TransformMatrix` group.
_MATRIX_INDEX = 0
#: Rejects a scale, shear or reflection in the reference's rotation block, which are
#: O(0.1) errors; emphatically not a precision policy. Matches the spirit of
#: ``SO101ClutchRetargeter``'s own orthonormality check.
_ORTHONORMAL_TOL = 1e-3
#: Below this a quaternion carries no usable orientation.
_MIN_QUAT_NORM = 1e-6


@dataclasses.dataclass(frozen=True)
class EngageGateConfig:
    """The band, the dwell, and how the frame delta is bounded.

    Only the *relation* between the two angles is pinned -- enter tighter than exit --
    because no absolute value here is defensible without a headset on a real operator.
    """

    #: Below this the gate may open. Radians.
    enter_rad: float = math.radians(20.0)
    #: Above this an open gate closes again. Radians; must be >= :attr:`enter_rad`.
    exit_rad: float = math.radians(30.0)
    #: How long every conjunct must hold before the gate goes green. Seconds.
    dwell_s: float = 0.1
    #: Frame period assumed when the graph clock does not advance. Seconds.
    nominal_dt: float = 1.0 / 60.0
    #: Upper clamp on the wall-clock frame delta, so a stalled graph cannot credit the
    #: dwell with the whole stall. Seconds.
    max_dt: float = 0.1

    def __post_init__(self) -> None:
        """Reject a configuration whose hysteresis is inverted or whose dwell is not a time.

        Raises:
            ValueError: If the band or the dwell is unusable.
        """
        if not 0.0 < self.enter_rad <= self.exit_rad:
            raise ValueError("require 0 < enter_rad <= exit_rad")
        if self.dwell_s < 0.0:
            raise ValueError("dwell_s must not be negative")
        if not 0.0 < self.nominal_dt <= self.max_dt:
            raise ValueError("require 0 < nominal_dt <= max_dt")


@dataclasses.dataclass(frozen=True)
class GateVerdict:
    """Whether the clutch may latch and -- when it may not -- why not.

    :attr:`failed` names **every** failing conjunct, not the first: an operator who
    fixes their wrist angle and immediately hits an unreported second failure has been
    told half the truth twice. Each entry is ``(key, phrase)``, kept as a pair so the
    value-free identity and the text it identifies cannot fall out of step.
    """

    #: ``key`` is value-free, so a caller can drive a state transition off it -- a
    #: rounded angle in the key would move it every frame. ``phrase`` carries the
    #: measurement, for display.
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


class EngageAlignmentGate(BaseRetargeter):
    """Gates a clutch's latch on wrist alignment, with hysteresis and a dwell.

    Inputs:
        - ``input_device`` -- Optional :func:`ControllerInput`; the orientation to judge.
        - :data:`REFERENCE_INPUT` -- Optional :func:`TransformMatrix`. **Only the
          rotation block is read**, and it must be in the same frame as the controller
          stream. Absent means "nothing to align against yet", reported as
          :data:`KEY_UNREFERENCED` rather than permitted.
        - :data:`ENGAGED_INPUT` -- Optional :func:`BoolFlag`; is the clutch latched, as
          of the previous frame? Unwired reads as False, which costs the post-release
          debounce and leaves only the dwell.
        - :data:`APP_PERMITTED_INPUT` -- Optional :func:`BoolFlag` for one extra
          conjunct the owner alone can evaluate. Fails **open**: unwired or absent is
          permitted.

    Outputs:
        - :data:`PERMITTED_OUTPUT` -- :func:`EngagePermission`, wire it straight to the
          clutch.

    The verdict behind that bool is not a graph output -- rendering ``(key, phrase)``
    pairs as tensors would buy nothing -- so read :attr:`verdict` after the step, the
    same way ``SO101ClutchRetargeter.is_engaged`` is read.
    """

    #: Input key for the pose the controller is judged against; rotation block only.
    REFERENCE_INPUT = "reference_pose"
    #: Input key for the owner's "the clutch is latched" flag. See the module docstring
    #: on why this is fed back rather than read, and on debouncing it.
    ENGAGED_INPUT = "engaged"
    #: Input key for one owner-supplied extra conjunct.
    APP_PERMITTED_INPUT = "app_permitted"
    #: Output key, and the name of the group it carries.
    PERMITTED_OUTPUT = "engage_permitted"
    #: Element index of the flag inside a :func:`BoolFlag` group.
    FLAG_INDEX = 0

    def __init__(
        self,
        name: str,
        *,
        input_device: str = ControllersSource.RIGHT,
        pose: HandPose = HandPose.GRIP,
        config: EngageGateConfig | None = None,
        app_conjunct: tuple[str, str] = ("app", "not ready"),
    ) -> None:
        """Initialize the gate, closed and with no dwell credit.

        Args:
            name: Name identifier for this retargeter node.
            input_device: Controller source key to read the pose from.
            pose: Which OpenXR controller pose carries the wrist orientation.
            config: Band, dwell and dt bounds; ``None`` uses the defaults.
            app_conjunct: The ``(key, phrase)`` reported when
                :data:`APP_PERMITTED_INPUT` is False. Naming it is the owner's job --
                only the owner knows what its conjunct means.
        """
        self._input_device = input_device
        self._pose = pose
        self._config = config or EngageGateConfig()
        self._app_conjunct = (str(app_conjunct[0]), str(app_conjunct[1]))
        self._ok = False
        self._dwell_s = 0.0
        self._last_time_ns: int | None = None
        self._verdict = GateVerdict(((KEY_UNJUDGED, "no frame judged yet"),))
        super().__init__(name=name)

    @property
    def verdict(self) -> GateVerdict:
        """The verdict computed on the **last** step.

        Before the first, :data:`KEY_UNJUDGED` -- never an empty verdict, which would
        read as "everything passed".
        """
        return self._verdict

    def input_spec(self) -> RetargeterIOType:
        """The controller, the reference pose, and the two owner-fed flags."""
        return {
            self._input_device: OptionalType(ControllerInput()),
            self.REFERENCE_INPUT: OptionalType(TransformMatrix()),
            self.ENGAGED_INPUT: OptionalType(BoolFlag(self.ENGAGED_INPUT)),
            self.APP_PERMITTED_INPUT: OptionalType(BoolFlag(self.APP_PERMITTED_INPUT)),
        }

    def output_spec(self) -> RetargeterIOType:
        """A single boolean permission, for the clutch's own optional input."""
        return {self.PERMITTED_OUTPUT: EngagePermission()}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Fold one frame in, publish the verdict, and emit the permission."""
        now_ns = int(context.graph_time.real_time_ns)
        dt = self._advance_clock(now_ns)
        engaged = self._flag(inputs, self.ENGAGED_INPUT, default=False)

        self._verdict = self._evaluate(inputs, engaged=engaged, dt=dt)
        outputs[self.PERMITTED_OUTPUT][self.FLAG_INDEX] = bool(
            engaged or self._verdict.ok
        )

    # ------------------------------------------------------------------ internals

    def _advance_clock(self, now_ns: int) -> float:
        """Frame delta [s], clamped; ``nominal_dt`` across a stalled or repeated stamp."""
        previous, self._last_time_ns = self._last_time_ns, now_ns
        if previous is None:
            return self._config.nominal_dt
        delta = (now_ns - previous) * 1e-9
        if delta <= 0.0:
            return self._config.nominal_dt
        return min(delta, self._config.max_dt)

    def _flag(self, inputs: RetargeterIO, key: str, *, default: bool) -> bool:
        """One optional boolean input, with the value an unwired one stands in for."""
        group = inputs.get(key)
        if group is None or group.is_none:
            return default
        return bool(group[self.FLAG_INDEX])

    def _evaluate(
        self, inputs: RetargeterIO, *, engaged: bool, dt: float
    ) -> GateVerdict:
        failed: list[tuple[str, str]] = []
        if engaged:
            failed.append((KEY_ENGAGED, "already engaged"))

        reference = _reference_rotation(inputs.get(self.REFERENCE_INPUT))
        if reference is None:
            failed.append((KEY_UNREFERENCED, "no reference pose"))

        # There is deliberately no reach conjunct: this judges orientation, and a
        # position residual would need a workspace envelope the gate cannot know.
        #
        # The rotation conjunct is judged only where both operands exist. Reporting an
        # angle derived from a missing operand would be a second failure caused by the
        # first, and the verdict is meant to list independent reasons.
        hand = _controller_rotation(inputs[self._input_device], self._pose)
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

        if not self._flag(inputs, self.APP_PERMITTED_INPUT, default=True):
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


def _reference_rotation(group) -> np.ndarray | None:
    """The 3x3 rotation block of a reference transform, or None if it cannot be used.

    A sheared or scaled block yields a plausible, wrong angle, so it is refused here
    rather than measured -- the caller reports it as "no reference pose", which is the
    truth from the gate's side.
    """
    if group is None or group.is_none:
        return None
    matrix = np.from_dlpack(group[_MATRIX_INDEX]).astype(np.float64)
    rotation = matrix[:3, :3]
    if not np.all(np.isfinite(rotation)):
        return None
    residual = rotation.T @ rotation - np.eye(3)
    if float(np.max(np.abs(residual))) > _ORTHONORMAL_TOL:
        return None
    return rotation


def _controller_rotation(group, pose: HandPose) -> np.ndarray | None:
    """The controller's orientation as a 3x3, or None when the pose is unusable."""
    _, orientation_index, valid_index = pose.indices
    if group.is_none or not bool(group[valid_index]):
        return None
    quat = np.asarray(group[orientation_index], dtype=np.float64)
    norm = float(np.linalg.norm(quat))
    if not np.isfinite(norm) or norm < _MIN_QUAT_NORM:
        return None
    return quat_xyzw_to_rotation_matrix(quat / norm)


def _geodesic_angle(a: np.ndarray, b: np.ndarray) -> float:
    """Angle [rad] of the rotation carrying ``a`` onto ``b``, in ``[0, pi]``.

    From the relative matrix's trace rather than through quaternions, which keeps this
    blind to the double cover and spares the gate a matrix-to-quaternion conversion of
    the reference.
    """
    cosine = (float(np.trace(a.T @ b)) - 1.0) / 2.0
    return float(np.arccos(min(1.0, max(-1.0, cosine))))
