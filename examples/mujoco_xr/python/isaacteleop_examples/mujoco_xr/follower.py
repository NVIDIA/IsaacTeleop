# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The SO-101 follower preview: the arm, the phase it is in, and whether the clutch may latch.

The joints are locked: ``qpos`` is written once, to :data:`Q_HOME`, and the arm is moved
as a rigid body. ``Follower._place`` is the one writer of ``body_quat`` and
``Follower._move_base`` the one writer of ``body_pos``. This module must not learn the
leader ghost's grip calibration, which is a claim about a hand holding a CONTROLLER;
app.py converts between the two.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import math

import mujoco
import numpy as np
from isaacteleop.retargeters.rate_limiter import _quat_geodesic_angle

from . import _mujoco_xr

LOG = logging.getLogger("mujoco_xr")

# Declared by assets/follower/follower_arm.xml and repointed onto every follower geom
# at startup, so the arm recolours in one write.
FOLLOWER_MATERIAL = "follower_arm"

BASE_BODY = "base"
GRIPPER_BODY = "gripper"

# Upstream's own tool frame, declared on the `gripper` body 98.4 mm out from its origin.
# The arm is placed BY this point, so it is also the axis the yaw turns about: it sits
# 3.8 mm off the closed jaw surface, where a grasped object would be. Placing by the
# gripper body instead pins a point 98.4 mm short of the jaw, which then swings on a
# 15.8 mm arc across +-90 degrees of yaw.
GRIPPER_SITE = "gripperframe"

# Upstream's joint order, which is also the qpos order Q_HOME is written in. Asserted
# by name at startup: a reordered upstream file would put each of Q_HOME's angles on a
# different joint and still look like an arm.
ARM_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
)
GRIPPER_JOINT = "gripper"

# The configuration the arm holds for the whole session, written to qpos once at
# construction. This pose IS the wrist posture the engage gate demands, so turning
# these re-aims the operator's hand. The arm is planar while J1 and J5 are zero, so
# the gripper's orientation is the SUM of J2, J3 and J4, and J4 stops at +-95 degrees.
Q_HOME_DEG = (
    0.00,  # J1 shoulder_pan  -- base yaw
    -45.00,  # J2 shoulder_lift -- first segment elevation
    45.00,  # J3 elbow_flex    -- second segment elevation
    90.00,  # J4 wrist_flex    -- wrist up/down
    -90.00,  # J5 wrist_roll    -- spin about the tool axis
    00.00,  # J6 gripper       -- jaw opening, 0 is the authored pose
)
Q_HOME = np.radians(Q_HOME_DEG)

# Where the home gripper sits relative to the OPERATOR'S HEAD, in XR axes: 0.30 m
# below eye level and 0.60 m ahead on the head's yaw-projected facing (anchor_from_head).
# Measured from the head, not the reference-space origin: the app does not get to choose
# that origin, and a stage-origin space puts anything authored against it a standing
# height out. Whether it lands inside the gaze cone is a headset judgement. Only the
# yaw of this anchor lasts the session -- it is the frame the grip offset below is
# carried on. The position holds only until the first frame carrying a controller,
# which owns all three axes from then on.
HOME_GRIP_FROM_HEAD_XR = np.array([0.0, -0.30, -0.60])

# Where the gripper's JAW sits relative to the CONTROLLER, in metres, XR axes: level
# with the hand laterally, 0.25 m ahead and 0.10 m below it (XR is y-up and -z-forward,
# cpp/frames.hpp). Only the starting value for the horizontal pair; the live one is
# Follower.grip_from_controller_xr, which the thumbstick walks. The vertical term is
# fixed. Carried on the anchor's yaw and never the wrist's, or turning the hand would
# swing the arm around the operator.
GRIP_FROM_CONTROLLER_XR = np.array([0.0, -0.10, -0.25])

# What the thumbstick does to the two horizontal terms above. Deflection is a RATE, so
# the offset holds where the stick left it. Metres per second at full deflection,
# scaled by the frame dt -- not per frame, or its feel would track the frame rate.
_TUNE_RATE_M_S = 0.20
# Sticks drift and the offset is latched, so a resting controller would walk the arm
# away over a session.
_STICK_DEADZONE = 0.15
# Each tuned term, absolutely: a stuck stick must not push the arm out of sight. The
# vertical term is not tuned and so not bounded here.
_TUNE_LIMIT_M = 0.60

# mjv_defaultOption enables geom groups 0-2 and disables 3-5, so this pair is "drawn"
# and "not drawn". A hidden geom never becomes an mjvGeom, so it never writes depth.
DRAWN_GROUP = 2
HIDDEN_GROUP = 3

# Engageable. The blocked colour is authored in follower_arm.xml: neutral grey, and
# darker at 0.45 against this one's 0.68 luminance. There is no HUD to fall back on, so
# brightness carries the signal as well as hue -- and a translucent arm dilutes both
# against whatever is behind it, so check the pair on a headset before trusting either.
_ENGAGEABLE_RGB = (0.20, 0.85, 0.35)

# ENGAGED is held while the hand channel is absent, so a one-frame tracking blip does
# not cost a teleport back onto the hand. This bounds the hold, so a genuinely lost
# controller cannot strand the app engaged.
_DROPOUT_TIMEOUT_S = 0.5

# The engage gate's one metric conjunct, with hysteresis. Only the RELATION is pinned
# -- enter tighter than exit -- because no value here is defensible without a headset.
_ROTATION_ENTER_RAD = math.radians(20.0)
_ROTATION_EXIT_RAD = math.radians(30.0)
# Time the gate must stay inside the enter band before it goes green.
_DWELL_S = 0.1


def yaw_of_direction(forward_xr: np.ndarray, fallback_xr: np.ndarray) -> np.ndarray:
    """The horizontal bearing of an XR direction, as a wxyz quaternion about +Y.

    ``fallback_xr`` covers a direction within a hair of vertical, which has no bearing to
    report. Every yaw reading goes through here, so all of them track a world-vertical
    turn 1:1; what differs between callers is only what leaks in from the other two
    degrees of freedom, which is a property of the axis they pick.
    """
    forward = np.asarray(forward_xr, dtype=float)
    if abs(forward[0]) < 1e-6 and abs(forward[2]) < 1e-6:
        # Straight up or down -- a headset face-down on a desk, a controller held
        # muzzle-up. The fallback then points along the horizon: forwards when the
        # direction points down, backwards when up.
        forward = -math.copysign(1.0, forward[1]) * np.asarray(fallback_xr, dtype=float)

    q_yaw = np.empty(4)
    mujoco.mju_axisAngle2Quat(
        q_yaw, np.array([0.0, 1.0, 0.0]), math.atan2(-forward[0], -forward[2])
    )
    return q_yaw


def yaw_of_axis(q_xyzw: np.ndarray, forward_local: np.ndarray) -> np.ndarray:
    """The horizontal facing of an XR orientation, as a wxyz quaternion about +Y.

    ``forward_local`` names which axis of the pose is its facing, in the pose's own
    frame. No default: each axis is blind to rotation about itself and sensitive to the
    rest, so it must be chosen against the motions the reading has to ignore. See
    app.py's _HAND_FORWARD_AXIS.
    """
    q_wxyz = np.asarray(q_xyzw, dtype=float)[[3, 0, 1, 2]]
    forward = np.empty(3)
    mujoco.mju_rotVecQuat(forward, np.asarray(forward_local, dtype=float), q_wxyz)
    up = np.empty(3)
    mujoco.mju_rotVecQuat(up, np.array([0.0, 1.0, 0.0]), q_wxyz)
    return yaw_of_direction(forward, up)


def yaw_of(q_xyzw: np.ndarray) -> np.ndarray:
    """The horizontal facing of a HEAD pose, reading its -Z as the view direction."""
    return yaw_of_axis(q_xyzw, np.array([0.0, 0.0, -1.0]))


def anchor_from_head(head_pose_xr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Where the home grip goes and which way the arm faces, from a 7-D head pose.

    Takes ``(position, xyzw)`` in XR; returns the XR home-grip position and the head's
    YAW as a wxyz quaternion. The same yaw does both jobs: it carries
    :data:`HOME_GRIP_FROM_HEAD_XR` onto the head's facing, and :meth:`Follower.anchor`
    turns the arm by it.
    """
    pose = np.asarray(head_pose_xr, dtype=float)
    q_yaw = yaw_of(pose[3:7])
    offset = np.empty(3)
    mujoco.mju_rotVecQuat(offset, HOME_GRIP_FROM_HEAD_XR, q_yaw)
    return pose[:3] + offset, q_yaw


def mj_from_xr_rotation(q_xr_wxyz: np.ndarray) -> np.ndarray:
    """An XR-frame ROTATION expressed in MuJoCo: ``Q q Q^-1``, wxyz throughout.

    Not ``_mujoco_xr.mj_from_xr_quat``, which maps a body's ORIENTATION across the
    frames and is a single left-multiply. Conjugating keeps the axis map with its one
    definition in cpp/frames.hpp: XR +Y is MuJoCo +z, so an XR yaw of theta comes out
    as a MuJoCo rotation of theta about +z.
    """
    q_frame = np.array(_mujoco_xr.QUAT_MJ_FROM_XR, dtype=float)
    inverse = np.empty(4)
    mujoco.mju_negQuat(inverse, q_frame)
    rotated = np.empty(4)
    mujoco.mju_mulQuat(rotated, q_frame, np.asarray(q_xr_wxyz, dtype=float))
    out = np.empty(4)
    mujoco.mju_mulQuat(out, rotated, inverse)
    return out


def set_geoms_visible(model, geoms: np.ndarray, visible: bool) -> None:
    """Add or remove ``geoms`` from what ``mjv_updateScene`` emits."""
    model.geom_group[geoms] = DRAWN_GROUP if visible else HIDDEN_GROUP


class ClutchPhase(enum.Enum):
    """Where the app is in the engage cycle, and so which tool it draws.

    Never the authority on "is the clutch latched?" -- that is
    ``SO101ClutchRetargeter.is_engaged``, which this is derived from.
    """

    #: The follower is drawn and dragged by the hand; the leader is hidden.
    DISENGAGED = "disengaged"
    #: The leader is drawn and follows the hand; the follower is hidden and frozen.
    ENGAGED = "engaged"


class PhaseMachine:
    """``DISENGAGED <-> ENGAGED``, one call per frame.

    Takes ``is_engaged`` as an input on every call and never copies it into a field,
    so the two cannot drift.
    """

    def __init__(self) -> None:
        """Start disengaged, with the arm already at Q_HOME."""
        self.phase = ClutchPhase.DISENGAGED
        #: Set on the disengage edge; the app clears it once it has pulsed the limiter.
        #: Without that pulse the limiter rejects the next ~30 frames -- its per-frame
        #: reject threshold at 72 Hz is only 27.8 mm.
        self.reset_requested = False
        self._dropout_s = 0.0

    def advance(
        self, *, is_engaged: bool, hand_present: bool, dt: float
    ) -> ClutchPhase:
        """Fold one frame in and return the new phase.

        ``is_engaged`` is read, never re-derived from the squeeze: the latch can be
        deferred by frames the app cannot observe. ``hand_present`` is what makes the
        disengage edge trustworthy -- ``is_engaged`` drops on four paths and only one
        of them is a real disengage.
        """
        if self.phase is ClutchPhase.DISENGAGED:
            if is_engaged:
                self.phase = ClutchPhase.ENGAGED
                self._dropout_s = 0.0
        elif not hand_present:
            # Hold ENGAGED through the gap. The clutch re-arms itself and re-latches at
            # _last_commanded_*, where the leader already is, so the resumed frame is
            # jump-free. Past the timeout the arm simply stays where it froze.
            self._dropout_s += dt
            if self._dropout_s > _DROPOUT_TIMEOUT_S:
                self._disengage()
        else:
            self._dropout_s = 0.0
            if not is_engaged:
                self._disengage()
        return self.phase

    def _disengage(self) -> None:
        self.phase = ClutchPhase.DISENGAGED
        self.reset_requested = True
        self._dropout_s = 0.0

    @property
    def permits_engagement(self) -> bool:
        """One disjunct of what the app feeds the clutch's latch gate.

        The other is the engage gate's verdict; the app sends ``permits_engagement or
        verdict.ok``. Reads the phase rather than ``is_engaged``: during a tracking
        dropout ``is_engaged`` is False on exactly the frames this exists to cover.
        """
        return self.phase is ClutchPhase.ENGAGED


#: The ``keys`` entry for the latched-clutch conjunct. While the clutch is latched
#: there is nothing to engage, so app.py logs no verdict carrying it.
GATE_KEY_ENGAGED = ClutchPhase.ENGAGED.value


@dataclasses.dataclass(frozen=True)
class GateResult:
    """Whether the clutch may latch, and -- when it may not -- why not.

    ``failed`` names **every** failing conjunct, not the first: an operator who fixes
    their wrist angle and immediately hits an unreported second failure has been told
    half the truth twice. Each entry is ``(key, phrase)``, kept as a pair so the
    value-free identity and the text it identifies cannot fall out of step.
    """

    #: ``key`` is app.py's transition key -- value-free, or a rounded angle in it
    #: would move the key every frame. ``phrase`` carries the measurement, for display.
    failed: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.failed)

    @property
    def blocked(self) -> tuple[str, ...]:
        return tuple(phrase for _, phrase in self.failed)


class EngageGate:
    """The three conjuncts of requirement 3, plus hysteresis and a dwell.

    Pure with respect to the app: it returns the failing conjuncts and app.py decides
    what to log.
    """

    def __init__(self) -> None:
        """Start closed, with no dwell credit."""
        self._ok = False
        self._dwell_s = 0.0

    def evaluate(
        self,
        *,
        phase: ClutchPhase,
        hand_quat_xyzw: np.ndarray | None,
        home_quat_xyzw: np.ndarray,
        limiter_passing: bool,
        dt: float,
    ) -> GateResult:
        """Fold one frame in.

        ``hand_quat_xyzw`` and ``home_quat_xyzw`` must share a layout -- the geodesic
        angle is layout-agnostic only under that condition, and both are xyzw in XR here.
        ``home_quat_xyzw`` carries the hand's own yaw, put there by :meth:`Follower.drive`,
        so the two cancel and what is left is the wrist's pitch and roll against a session
        constant.
        """
        failed: list[tuple[str, str]] = []
        # The whole post-release debounce: `ok` is held False for the entire
        # engagement, so the dwell below is zeroed on every engaged frame and a release
        # cannot re-latch for at least _DWELL_S. It is also why the app must feed the
        # clutch `permits_engagement or verdict.ok`.
        if phase is ClutchPhase.ENGAGED:
            failed.append((GATE_KEY_ENGAGED, phase.value))
        theta = math.inf
        if hand_quat_xyzw is None:
            failed.append(("untracked", "controller not tracked"))
        else:
            theta = _quat_geodesic_angle(
                np.asarray(hand_quat_xyzw, dtype=float),
                np.asarray(home_quat_xyzw, dtype=float),
            )

        # There is no reach conjunct and no reach envelope. The gripper is placed
        # exactly at its offset from the hand every frame, so a position residual is
        # zero by construction. Do not add one back believing it bounds a workspace:
        # this preview has none.
        rotation_tol = _ROTATION_EXIT_RAD if self._ok else _ROTATION_ENTER_RAD
        # Only against a tracked hand: with none there is no angle, and reporting one
        # would be a second failure derived from the first.
        if hand_quat_xyzw is not None and not theta < rotation_tol:
            failed.append(
                (
                    "rotation",
                    f"rotation {math.degrees(theta):.0f} deg "
                    f"> {math.degrees(rotation_tol):.0f}",
                )
            )
        # The leader renders the LIMITER's output, so a gate that opens while it is
        # still clamping reveals a tool tens of degrees and hundreds of milliseconds
        # behind the hand. 4 deg/cm x 0.5 m/s is 3.49 rad/s against a 2.5 rad/s clamp,
        # so this trips at about 0.36 m/s of hand speed -- ordinary dragging.
        if not limiter_passing:
            failed.append(("limiter", "still catching up"))

        if failed:
            self._dwell_s = 0.0
            self._ok = False
            return GateResult(tuple(failed))

        self._dwell_s += dt
        if self._dwell_s < _DWELL_S:
            return GateResult((("settling", "settling"),))
        self._ok = True
        return GateResult()


class Follower:
    """The follower arm in one scene: posed once, drawn, and driven rigidly by the hand.

    :meth:`drive` moves it two independent ways: position from the controller plus a
    thumbstick-trimmed offset, yaw from the wrist. Placed by :data:`GRIPPER_SITE`,
    upstream's tool frame at the jaw, which is therefore also the axis the yaw turns
    about; the gripper body carries the orientation and sits 98.4 mm short of it.
    """

    def __init__(self, model, data) -> None:
        """Resolve the arm, check its qpos layout and pose it. NOT yet placed."""
        self._model = model
        self._data = data

        self._base = _body(model, BASE_BODY)
        self._gripper = _body(model, GRIPPER_BODY)
        self._jaw = _site(model, GRIPPER_SITE)
        # Kept because the anchor composes its yaw onto it rather than replacing it,
        # so a scene that authors a base tilt keeps it.
        self._authored_base_quat = np.array(model.body_quat[self._base], dtype=float)
        _check_qpos_layout(model)

        self._material = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_MATERIAL, FOLLOWER_MATERIAL
        )
        if self._material < 0:
            raise RuntimeError(
                f"mujoco_xr: the scene declares no `{FOLLOWER_MATERIAL}` material; it must "
                "<include> assets/follower/follower_arm.xml rather than upstream's MJCF directly."
            )
        self._geoms = _subtree_geoms(model, self._base)
        self._visual_geoms = self._geoms[model.geom_group[self._geoms] == DRAWN_GROUP]
        if self._visual_geoms.size == 0:
            # Upstream numbers its visual geoms 2 and its collision geoms 3. A
            # renumbering has to be an error, not a silently invisible arm.
            raise RuntimeError(
                f"mujoco_xr: no follower geom is in group {DRAWN_GROUP}, so the arm would "
                "never be drawn; upstream's geom groups changed."
            )
        # One material for thirteen upstream ones, on every follower geom rather than
        # just the drawn ones, so the rule has no exception to remember.
        model.geom_matid[self._geoms] = self._material
        self._blocked_rgba = np.array(model.mat_rgba[self._material], dtype=np.float64)

        # The one and only qpos write. Everything after this moves the base.
        self._data.qpos[: len(Q_HOME)] = Q_HOME
        self._jaw_from_base = self._measure_jaw_from_base()

        # The live grip offset. This class is its only definition; app.py passes two raw
        # stick axes and never learns which way either points.
        self._grip_from_controller_xr = GRIP_FROM_CONTROLLER_XR.copy()
        # Whether the stick has moved the offset since it was last at rest, so the tuned
        # value is logged once on the release rather than at 72 Hz.
        self._tuning = False

        # The frame the offset is carried on. None until anchor() takes it off the head,
        # which is also what `anchored` reports.
        self._anchored = False
        # The yaw the base is currently turned by -- the wrist's, past the first driven
        # frame, and so not the operator's above.
        self._base_yaw_xr = np.array([1.0, 0.0, 0.0, 0.0])
        self.set_visible(False)

    # ---------------------------------------------------------------- geometry

    @property
    def anchored(self) -> bool:
        """Whether a head pose has placed the arm. False until then; never back."""
        return self._anchored

    @property
    def base_yaw_xr(self) -> np.ndarray:
        """The XR yaw (wxyz) the base is currently turned by; identity before any.

        Past the first driven frame this is the wrist's yaw, not the operator's. Kept as
        the value that was used rather than read back off ``body_quat``.
        """
        return self._base_yaw_xr.copy()

    def anchor(self, head_pose_xr: np.ndarray) -> np.ndarray:
        """Take the offset's frame off the first head pose, and park the arm.

        Returns the XR home grip. Where the arm waits until a controller arrives, and the
        head's yaw is only what turns it to face the operator meanwhile -- from the first
        driven frame the controller owns both position and yaw.
        """
        home_xr, q_yaw_xr = anchor_from_head(head_pose_xr)
        self._anchored = True
        self._place(home_xr, q_yaw_xr)
        LOG.info(
            "follower:   anchored to a head at XR (%.2f, %.2f, %.2f) facing %.0f deg; "
            "home grip at XR (%.2f, %.2f, %.2f), base at MuJoCo (%.3f, %.3f, %.3f). "
            "The controller owns both from the first driven frame.",
            *np.asarray(head_pose_xr, dtype=float)[:3],
            math.degrees(2.0 * math.atan2(q_yaw_xr[2], q_yaw_xr[0])),
            *home_xr,
            *self._model.body_pos[self._base],
        )
        return home_xr

    def reset_offset(self) -> None:
        """Put the grip offset back to :data:`GRIP_FROM_CONTROLLER_XR`. Any phase.

        The operator's escape hatch for an offset walked out to its clamp, or a drifting
        stick that got there on its own. Nothing else to reset: the arm is already on
        the hand and already on its yaw.
        """
        self._grip_from_controller_xr = GRIP_FROM_CONTROLLER_XR.copy()
        self._tuning = False

    def _place(self, grip_xr: np.ndarray, q_yaw_xr: np.ndarray) -> None:
        """Turn the base onto a yaw and put the gripper on an XR point. Does both, always.

        The order is load-bearing: turning the base swings the gripper around it, so
        ``_jaw_from_base`` is re-measured between the ``body_quat`` and ``body_pos``
        writes. That second ``mj_forward`` costs 202 us a frame on a Jetson AGX Orin,
        1.5% of a 72 Hz frame -- cheap enough to keep the offset measured, not derived.
        """
        # Yaw on the LEFT: it turns the arm in the WORLD, where upstream's quat orients
        # it in its own frame. Upstream authors identity, so no shipped scene can tell
        # the two orders apart -- this comment is the only guard.
        turned = np.empty(4)
        mujoco.mju_mulQuat(
            turned, mj_from_xr_rotation(q_yaw_xr), self._authored_base_quat
        )
        self._model.body_quat[self._base] = turned
        self._base_yaw_xr = np.asarray(q_yaw_xr, dtype=float).copy()
        self._jaw_from_base = self._measure_jaw_from_base()
        self._move_base(
            np.array(_mujoco_xr.mj_from_xr_pos(list(grip_xr)), dtype=float)
            - self._jaw_from_base
        )

    def _measure_jaw_from_base(self) -> np.ndarray:
        """Base origin -> the jaw tool frame in MuJoCo world. Measured, never derived.

        With the base at the MuJoCo origin the site's world position is the offset. Only
        the base's yaw can change it, so only :meth:`_place` calls this -- and it must
        write ``body_pos`` afterwards, because this leaves the base at the origin. Goes
        through ``_move_base``, the one writer of ``body_pos``.
        """
        self._move_base(np.zeros(3))
        return np.array(self._data.site_xpos[self._jaw], dtype=float)

    def _move_base(self, base_pos_mj: np.ndarray) -> None:
        """Slide the whole arm. The one place ``body_pos`` is written.

        ``base`` is a fixed child of world, so every link translates with it and no
        joint moves. Never touches ``body_quat``: :meth:`_place` is that one writer.
        """
        self._model.body_pos[self._base] = base_pos_mj
        mujoco.mj_forward(self._model, self._data)

    @property
    def jaw_yaw_xr(self) -> np.ndarray:
        """The XR yaw (wxyz) the jaw faces along: :data:`GRIPPER_SITE`'s +Z.

        Which way the gripper is turned, and what app.py aims at the controller. Not the
        links' reach: J5 rolls the jaw about the tool axis without moving them, so the
        two part company by exactly that roll. The site's +X is the tool axis and points
        down at Q_HOME, which is why a roll there reads as a bearing change here.
        """
        facing = np.array(self._data.site_xmat[self._jaw], dtype=float).reshape(3, 3)[
            :, 2
        ]
        inverse = np.empty(4)
        mujoco.mju_negQuat(inverse, np.array(_mujoco_xr.QUAT_MJ_FROM_XR, dtype=float))
        facing_xr = np.empty(3)
        mujoco.mju_rotVecQuat(facing_xr, facing, inverse)
        return yaw_of_direction(facing_xr, np.array([0.0, 0.0, -1.0]))

    def gripper_pose_mj(self) -> tuple[np.ndarray, np.ndarray]:
        """The gripper body's ``(pos, quat_wxyz)`` in MuJoCo world coordinates.

        Callers want the orientation: it is what the gate demands of the wrist and what
        the clutch latches. The position is the body's, 98.4 mm short of the jaw the arm
        is placed by, so do not read it as the tool point.
        """
        return (
            np.array(self._data.xpos[self._gripper], dtype=float),
            np.array(self._data.xquat[self._gripper], dtype=float),
        )

    # ------------------------------------------------------------------ drives

    def drive(
        self,
        hand_pos_xr: np.ndarray,
        q_facing_xr: np.ndarray,
        q_base_yaw_xr: np.ndarray,
        stick_x: float,
        stick_y: float,
        dt: float,
    ) -> None:
        """One disengaged frame: the jaw at the live grip offset off ``hand_pos_xr``, the
        base on ``q_base_yaw_xr``.

        Both land on :data:`GRIPPER_SITE`, so the yaw turns the arm about the jaw. Both
        yaws arrive already computed: deriving them needs the grip calibration, which this
        module does not get to learn. ``q_facing_xr`` is where the controller points and
        ``q_base_yaw_xr`` what to turn the base onto; they differ by app.py's measured
        bias. Only legal once :attr:`anchored` and while DISENGAGED -- an offset moving
        while the arm is frozen applies its excursion on the release frame.
        """
        self._walk(stick_x, stick_y, dt)
        # A direction, so it crosses onto the yaw by rotation alone. The CONTROLLER'S
        # facing, so the offset is what the operator sees: stick forward sends the arm
        # away along the pointing ray, and yawing the controller carries the arm around
        # with it at a fixed relative position. Not the BASE yaw, which leads the facing
        # by the bias and would send "forward" off by that much. A yaw leaves the vertical
        # term untouched, so this one rotate is correct for all three.
        offset = np.empty(3)
        mujoco.mju_rotVecQuat(offset, self._grip_from_controller_xr, q_facing_xr)
        self._place(np.asarray(hand_pos_xr, dtype=float) + offset, q_base_yaw_xr)

    @property
    def grip_from_controller_xr(self) -> np.ndarray:
        """The live gripper-from-controller offset in XR axes, tuning included."""
        return self._grip_from_controller_xr.copy()

    def _walk(self, stick_x: float, stick_y: float, dt: float) -> None:
        """Walk the offset's two horizontal terms at the thumbstick's deflection.

        The caller passes raw stick axes and this decides where they point: OpenXR's
        stick is +x right and +y forward while XR is +x right and -z forward, so x follows
        the stick and z opposes it. Both are read in the CONTROLLER's frame by
        :meth:`drive`, so forward is further along the pointing ray. The vertical term is
        never touched.
        """
        step = _TUNE_RATE_M_S * float(dt)
        delta = np.array([deflection(stick_x) * step, 0.0, -deflection(stick_y) * step])
        if not delta.any():
            if self._tuning:
                self._tuning = False
                # In the constant's own form, so a headset session ends in a value that
                # can be pasted back into this file.
                LOG.info(
                    "follower:   offset tuned to GRIP_FROM_CONTROLLER_XR = "
                    "np.array([%.2f, %.2f, %.2f])",
                    *self._grip_from_controller_xr,
                )
            return
        tuned = self._grip_from_controller_xr + delta
        # Indexed rather than whole-vector: the vertical term is not tuned, so it must
        # not be bounded by a limit chosen for the horizontal ones.
        tuned[[0, 2]] = np.clip(tuned[[0, 2]], -_TUNE_LIMIT_M, _TUNE_LIMIT_M)
        self._grip_from_controller_xr = tuned
        self._tuning = True

    # -------------------------------------------------------------- appearance

    def set_visible(self, visible: bool) -> None:
        """Draw the arm, or not. Its collision geoms are never drawn either way.

        An un-anchored arm cannot be shown at all: drawing it against the
        reference-space origin is the bug the anchor exists to fix. Enforced here
        rather than only at the call site.
        """
        set_geoms_visible(self._model, self._visual_geoms, visible and self.anchored)

    def set_engageable(self, engageable: bool) -> None:
        """Green when the clutch would latch on a squeeze, the authored colour otherwise."""
        rgba = self._blocked_rgba.copy()
        if engageable:
            rgba[:3] = _ENGAGEABLE_RGB
        self._model.mat_rgba[self._material] = rgba

    def log_placement(self) -> None:
        """One line naming the placement rule, before any head pose exists."""
        LOG.info(
            "follower:   SO-101 home grip %.2f m below and %.2f m in front of the HEAD, "
            "turned onto its facing, on the first frame carrying one. Hidden until then. "
            "After it: the JAW dragged rigidly by the controller at (%.2f, %.2f, %.2f) "
            "off it, turning about itself on the wrist's own yaw, with the right "
            "thumbstick trimming the horizontal pair to +-%.2f m.",
            -HOME_GRIP_FROM_HEAD_XR[1],
            -HOME_GRIP_FROM_HEAD_XR[2],
            *GRIP_FROM_CONTROLLER_XR,
            _TUNE_LIMIT_M,
        )


def deflection(axis: float) -> float:
    """One stick axis past the deadzone, or zero inside it. NaN reads as inside.

    Spelled ``not >=`` rather than ``<`` so a non-finite axis falls inside: everything
    the stick drives is latched, so one bad frame would poison it for the whole session.
    Public because app.py's yaw trim integrates the same axis under the same deadzone.
    """
    value = float(axis)
    return 0.0 if not abs(value) >= _STICK_DEADZONE else value


def _site(model, name: str) -> int:
    site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, name)
    if site < 0:
        raise RuntimeError(
            f"mujoco_xr: the scene declares no `{name}` site; upstream's MJCF stopped "
            "publishing its tool frame, and the arm has no point to be placed by."
        )
    return site


def _body(model, name: str) -> int:
    body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)
    if body < 0:
        raise RuntimeError(
            f"mujoco_xr: the scene declares no `{name}` body; it must <include> "
            "assets/follower/follower_arm.xml."
        )
    return body


def _subtree_geoms(model, root: int) -> np.ndarray:
    """Every geom on ``root`` and its descendants, by geom id.

    ``body_rootid`` is the top of the kinematic tree a body belongs to, so this holds
    exactly while ``root`` is a direct child of world -- which the scene guarantees.
    """
    return np.where(model.body_rootid[model.geom_bodyid] == root)[0].astype(np.int32)


def _check_qpos_layout(model) -> None:
    """What licenses writing ``Q_HOME`` straight into ``qpos[:6]``.

    The follower must be the scene's only jointed body, in upstream's order, so a
    scene that gains a second one fails here rather than landing Q_HOME's angles on
    somebody else's joints.
    """
    names = tuple(ARM_JOINTS) + (GRIPPER_JOINT,)
    if not (model.nq == model.njnt == len(names)):
        raise RuntimeError(
            f"mujoco_xr: expected {len(names)} hinge DOFs and nothing else, got "
            f"nq={model.nq} njnt={model.njnt}."
        )
    for index, expected in enumerate(names):
        actual = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, index)
        if actual != expected:
            raise RuntimeError(
                f"mujoco_xr: joint {index} is `{actual}`, expected `{expected}`; upstream's "
                "joint order changed and Q_HOME would pose the wrong joints."
            )
        # Q_HOME is six angles in radians; a slide joint would read them as metres.
        # Hinges take one qpos slot each, so this is also what makes the addresses
        # 0..5 and lets Q_HOME be written as a slice.
        if model.jnt_type[index] != mujoco.mjtJoint.mjJNT_HINGE:
            raise RuntimeError(f"mujoco_xr: joint `{actual}` is not a hinge.")
