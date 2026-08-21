# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The SO-101 follower preview: the arm, the phase it is in, and whether the clutch may latch.

The joints are locked: they are written once, to :data:`Q_HOME`, and the arm is moved as
a rigid body. :meth:`Follower._place` is the one place its base pose is published, and
every other frame on the arm is that pose composed with a constant measured at
:data:`Q_HOME`. This module must not learn the leader ghost's grip calibration, which is
a claim about a hand holding a CONTROLLER; app.py converts between the two.
"""

from __future__ import annotations

import enum
import logging
import math

import numpy as np
from isaacteleop.viz.robot import anchor_from_head, frames, yaw_of_direction
from isaacteleop.viz.robot.quaternion import conjugate, multiply, rotate
from isaacteleop.viz.robot.scene import WORLD_BODY

LOG = logging.getLogger("robot_viz")

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
# these re-aims the operator's hand, so re-solve _EULER_HAND_FROM_GHOST_DEG with them.
# J2+J3+J4 set the gripper's elevation and J4 stops at +-95 degrees; J5 rolls the jaw
# about the tool axis, which is a bearing shift in the posture the gate demands.
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
# height out. Whether it lands inside the gaze cone is a headset judgement. A starting
# pose only: the position holds until the first frame carrying a controller, and the yaw
# only turns the arm to face the operator meanwhile. The controller owns both after it.
HOME_GRIP_FROM_HEAD_XR = np.array([0.0, -0.30, -0.60])

# Where the gripper's JAW sits relative to the CONTROLLER, in metres, XR axes: level
# with the hand laterally, 0.25 m ahead and 0.10 m below it (XR is y-up and -z-forward,
# viz.robot.frames). Only the starting value for the horizontal pair; the live one is
# Follower.grip_from_controller_xr, which the thumbstick walks. The vertical term is
# fixed. Carried on the controller's own facing, so stick forward sends the arm along
# the pointing ray and yawing the controller carries it around at a fixed offset.
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

#: The twin's name for every geom on the arm, declared at construction.
FOLLOWER_GROUP = "follower"

# Engageable. The blocked colour is authored in follower_arm.xml: neutral grey, and
# darker at 0.45 against this one's 0.68 luminance. There is no HUD to fall back on, so
# brightness carries the signal as well as hue -- and a translucent arm dilutes both
# against whatever is behind it, so check the pair on a headset before trusting either.
_ENGAGEABLE_RGB = (0.20, 0.85, 0.35)

# ENGAGED is held while the hand channel is absent, so a one-frame tracking blip does
# not cost a teleport back onto the hand. This bounds the hold, so a genuinely lost
# controller cannot strand the app engaged.
_DROPOUT_TIMEOUT_S = 0.5


def mj_from_xr_rotation(q_xr_wxyz: np.ndarray) -> np.ndarray:
    """An XR-frame ROTATION expressed in MuJoCo: ``Q q Q^-1``, wxyz throughout.

    Not ``frames.mj_from_xr_quat``, which maps a body's ORIENTATION across the
    frames and is a single left-multiply. Conjugating keeps the axis map with its one
    definition in viz.robot.frames: XR +Y is MuJoCo +z, so an XR yaw of theta comes out
    as a MuJoCo rotation of theta about +z.
    """
    q_frame = np.array(frames.QUAT_MJ_FROM_XR, dtype=float)
    inverse = conjugate(q_frame)
    rotated = multiply(q_frame, np.asarray(q_xr_wxyz, dtype=float))
    out = multiply(rotated, inverse)
    return out


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


class Follower:
    """The follower arm in one scene: posed once, drawn, and driven rigidly by the hand.

    :meth:`drive` moves it two independent ways: position from the controller plus a
    thumbstick-trimmed offset, yaw from the wrist. Placed by :data:`GRIPPER_SITE`,
    upstream's tool frame at the jaw, which is therefore also the axis the yaw turns
    about; the gripper body carries the orientation and sits 98.4 mm short of it.
    """

    def __init__(self, twin) -> None:
        """Resolve the arm in ``twin``, pose it at :data:`Q_HOME`, and hide it.

        Everything the arm's geometry is ever asked for is measured here, in that
        posture: the arm is rigid below it, so its links move exactly as its base does
        and a live lookup would answer the same thing more expensively.
        """
        self._twin = twin

        included = (
            "It must <include> assets/follower/follower_arm.xml rather than "
            "upstream's MJCF directly."
        )
        # The follower must be the scene's only jointed body, in upstream's order, so a
        # scene that gains a second one fails here rather than landing Q_HOME's angles
        # on somebody else's joints.
        twin.joints.require(ARM_JOINTS + (GRIPPER_JOINT,))

        # Upstream numbers its visual geoms 2 and its collision geoms 3, and a
        # renumbering has to be an error rather than a silently invisible arm --
        # declare_group raises on an empty set.
        twin.declare_group(FOLLOWER_GROUP, body=BASE_BODY, drawn_only=True)
        # One material for thirteen upstream ones, so the arm recolours in one write.
        self._blocked_rgba = twin.declare_material(FOLLOWER_MATERIAL, hint=included)
        twin.repaint(FOLLOWER_GROUP, FOLLOWER_MATERIAL)

        # The one and only joint write. Everything after this moves the base.
        twin.home(Q_HOME)

        # Where the base was authored. The anchor composes its yaw onto this rather
        # than replacing it, so a scene that authors a base tilt keeps it.
        self._base_pos, self._authored_base_quat = twin.body_offset(
            BASE_BODY, relative_to=WORLD_BODY
        )
        self._base_quat = self._authored_base_quat.copy()

        # The two constants Q_HOME freezes, both in the BASE's own frame. Composing the
        # base's pose with them is what replaces every per-frame forward-kinematics
        # read; see twin.py on why there is no live equivalent.
        jaw_pos, jaw_quat = twin.site_offset(
            GRIPPER_SITE,
            relative_to=BASE_BODY,
        )
        self._jaw_from_base_local = jaw_pos
        # The site's +Z is the direction the jaw faces; its +X is the tool axis.
        self._jaw_facing_local = rotate(np.array([0.0, 0.0, 1.0]), jaw_quat)
        self._gripper_from_base_local = twin.body_offset(
            GRIPPER_BODY, relative_to=BASE_BODY
        )

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
        home_xr, q_yaw_xr = anchor_from_head(head_pose_xr, HOME_GRIP_FROM_HEAD_XR)
        self._anchored = True
        self._place(home_xr, q_yaw_xr)
        LOG.info(
            "follower:   anchored to a head at XR (%.2f, %.2f, %.2f) facing %.0f deg; "
            "home grip at XR (%.2f, %.2f, %.2f), base at MuJoCo (%.3f, %.3f, %.3f). "
            "The controller owns both from the first driven frame.",
            *np.asarray(head_pose_xr, dtype=float)[:3],
            math.degrees(2.0 * math.atan2(q_yaw_xr[2], q_yaw_xr[0])),
            *home_xr,
            *self._base_pos,
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
        """Turn the base onto a yaw and put the jaw on an XR point. Does both, always.

        The order is load-bearing but no longer costs a forward-kinematics pass: turning
        the base swings the jaw around it, so the offset is the load-time constant
        rotated by the new base orientation. One publish, both fields.
        """
        # Yaw on the LEFT: it turns the arm in the WORLD, where upstream's quat orients
        # it in its own frame. Upstream authors identity, so no shipped scene can tell
        # the two orders apart -- this comment is the only guard.
        turned = multiply(mj_from_xr_rotation(q_yaw_xr), self._authored_base_quat)
        self._base_quat = turned
        self._base_yaw_xr = np.asarray(q_yaw_xr, dtype=float).copy()
        self._base_pos = (
            np.array(frames.mj_from_xr_pos(list(grip_xr)), dtype=float)
            - self.jaw_from_base
        )
        self._twin.publish(bodies={BASE_BODY: (self._base_pos, self._base_quat)})

    @property
    def jaw_from_base(self) -> np.ndarray:
        """Base origin -> the jaw tool frame, in MuJoCo world axes.

        The load-time constant turned by the base's current orientation, which is the
        whole of how it can change: the arm is rigid, so nothing below the base moves
        relative to it.
        """
        return rotate(self._jaw_from_base_local, self._base_quat)

    @property
    def jaw_yaw_xr(self) -> np.ndarray:
        """The XR yaw (wxyz) the jaw faces along: :data:`GRIPPER_SITE`'s +Z.

        Which way the gripper is turned, and what app.py aims at the controller. Not the
        links' reach: J5 rolls the jaw about the tool axis without moving them, so the
        two part company by exactly that roll. The site's +X is the tool axis and points
        down at Q_HOME, which is why a roll there reads as a bearing change here.
        """
        facing = rotate(self._jaw_facing_local, self._base_quat)
        inverse = conjugate(np.array(frames.QUAT_MJ_FROM_XR, dtype=float))
        facing_xr = rotate(facing, inverse)
        return yaw_of_direction(facing_xr, np.array([0.0, 0.0, -1.0]))

    def gripper_pose_mj(self) -> tuple[np.ndarray, np.ndarray]:
        """The gripper body's ``(pos, quat_wxyz)`` in MuJoCo world coordinates.

        Callers want the orientation: it is what the gate demands of the wrist and what
        the clutch latches. The position is the body's, 98.4 mm short of the jaw the arm
        is placed by, so do not read it as the tool point.
        """
        local_pos, local_quat = self._gripper_from_base_local
        quat = multiply(self._base_quat, local_quat)
        return self._base_pos + rotate(local_pos, self._base_quat), quat

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
        offset = rotate(self._grip_from_controller_xr, q_facing_xr)
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
        self._twin.publish(groups={FOLLOWER_GROUP: visible and self.anchored})

    def set_engageable(self, engageable: bool) -> None:
        """Green when the clutch would latch on a squeeze, the authored colour otherwise."""
        rgba = self._blocked_rgba.copy()
        if engageable:
            rgba[:3] = _ENGAGEABLE_RGB
        self._twin.publish(materials={FOLLOWER_MATERIAL: rgba})

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
