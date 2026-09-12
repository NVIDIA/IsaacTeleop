# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The arm the operator drags by hand before the clutch engages.

The joints are written once, to the profile's ``q_home``, and the arm is moved as a rigid
body: :meth:`PreviewArm._place` is the one place its base pose is published, and every
other frame on the arm is that pose composed with a constant measured at that pose. This
module must not learn the leader ghost's grip calibration, which is a claim about a hand
holding a controller; :mod:`.so101_ghost` converts between the two.

Which arm is profile data -- see :data:`PREVIEW_ARMS`. Each arm previews the pose its real
follower parks at, and carries both the gripper it puts on the operator's hand and the
calibration that places it, solved against that pose.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import frames
from .anchor import anchor_from_head, yaw_of_direction
from .quaternion import conjugate, multiply, rotate
from .ghost import REBOT_GHOST, GhostSpec
from .scene import WORLD_BODY
from .so101_ghost import SO101_GHOST, quat_hand_from_ghost

LOG = logging.getLogger(__name__)

# Declared by each profile's scene wrapper and repointed onto every follower geom at
# startup, so the arm recolours in one write.
FOLLOWER_MATERIAL = "follower_arm"

# Each arm previews the pose its real follower parks at on declutch, so the operator sees
# the arm hold what the hardware will hold. These are LeRobot's RobotProfile.reset_pose for
# the same arm, in that arm's own joint order; keep the two in step.
#
# The pose does NOT set the wrist the engage gate demands -- the arm's
# euler_hand_from_ghost_deg does, and the two are solved together. Move a pose and the gate
# follows it unless the calibration is re-solved with it (so101_ghost has the closed form).

# SO-101, in motor order -- here the URDF joint names, the motor names and the qpos order
# all coincide. J4 stops at +-95 degrees.
#
# wrist_roll is the one joint whose zero the arm's calibration does not pin: LeRobot forces
# its range to a full turn, so normalized 0 is wherever the wrist sat at the homing prompt
# rather than a mechanical feature. Measured across two calibrations of one arm: every other
# joint's zero reproduced within 2 deg, wrist_roll moved 90. So if the preview's gripper
# looks rolled against the hardware, recalibrate holding the wrist where this pose puts it
# -- do not "fix" the number below, which is right for a correctly homed arm and wrong for
# the next one.
Q_HOME_DEG = (
    0.00,  # J1 shoulder_pan  -- base yaw
    -45.00,  # J2 shoulder_lift -- first segment elevation
    45.00,  # J3 elbow_flex    -- second segment elevation
    90.00,  # J4 wrist_flex    -- wrist up/down
    0.00,  # J5 wrist_roll    -- spin about the tool axis
    0.00,  # J6 gripper       -- jaw opening, 0 is the authored pose
)
Q_HOME = np.radians(Q_HOME_DEG)

# reBot DevArm. jointN is the MJCF/URDF name; the motor it drives is named beside it, in
# the positional order LeRobot's IK already maps by. The gripper is a pair of slides this
# does not address.
Q_HOME_REBOT_DEG = (
    0.00,  # joint1 -- shoulder_pan
    -5.00,  # joint2 -- shoulder_lift, 5 deg off the endpoint it calibrates at
    -10.00,  # joint3 -- elbow_flex, 10 deg off its endpoint
    0.00,  # joint4 -- wrist_flex
    0.00,  # joint5 -- wrist_yaw
    0.00,  # joint6 -- wrist_roll
)
Q_HOME_REBOT = np.radians(Q_HOME_REBOT_DEG)


@dataclass(frozen=True)
class PreviewArmProfile:
    """One follower's scene and the names :class:`PreviewArm` addresses it by.

    Adding an arm is an entry in :data:`PREVIEW_ARMS`, not a code change. Everything here
    is read off the compiled model or authored in its scene; nothing is tuned by eye.
    """

    name: str
    """The key this profile is selected by on a command line."""

    label: str
    """What the startup log calls the arm."""

    scene: Callable[[], Path]
    """Returns the scene path, fetching and caching it on first use."""

    joints: tuple[str, ...]
    """Every hinge the scene declares, in qpos order -- asserted by name at startup, since
    a reordered upstream file would land ``q_home`` on the wrong joints and still look like
    an arm. Slide joints are not addressed and so are not named here."""

    q_home: np.ndarray
    """Radians, parallel to :attr:`joints`. The one and only joint write."""

    base_body: str
    """The body the whole arm is moved by."""

    gripper_body: str
    """The gripper body, whose pose the ghost handoff is taken from."""

    ghost: GhostSpec
    """The gripper this arm puts on the operator's hand once the clutch engages."""

    euler_hand_from_ghost_deg: tuple[float, float, float]
    """Where the leader ghost sits on the hand, for this arm. Paired with :attr:`q_home`:
    it turns that pose's gripper orientation into the hand the engage gate demands, so the
    two move together. See :mod:`.so101_ghost` for the closed form."""

    tool: str | tuple[str, np.ndarray, np.ndarray]
    """The point the arm is placed by, and so the axis its yaw turns about: a site name, or
    a ``(body, pos, quat)`` frame in that body's own frame for a scene that declares no
    site. Placing by the gripper body instead swings the jaw on an arc across the yaw
    range. The frame's +Z is the direction the jaw faces."""


def _so101_scene() -> Path:
    from . import assets

    return assets.ensure_so101_scene()


def _rebot_devarm_rs_scene() -> Path:
    from . import assets

    return assets.ensure_rebot_devarm_rs_scene()


_PROFILES = (
    PreviewArmProfile(
        name="so101",
        label="SO-101",
        scene=_so101_scene,
        joints=(
            "shoulder_pan",
            "shoulder_lift",
            "elbow_flex",
            "wrist_flex",
            "wrist_roll",
            "gripper",
        ),
        q_home=Q_HOME,
        base_body="base",
        gripper_body="gripper",
        ghost=SO101_GHOST,
        # Unchanged by the move to a park-pose Q_HOME: wrist_roll rolls about the tool
        # axis, and the clutch measures that bias at every engage, so the wrist the gate
        # demands is the same at 0 as it was at -90.
        euler_hand_from_ghost_deg=(270.0, 0.0, 90.0),
        # Upstream's own tool frame, declared on the `gripper` body 98.4 mm out from its
        # origin and 3.8 mm off the closed jaw surface.
        tool="gripperframe",
    ),
    PreviewArmProfile(
        # The build is in the name because it has to be: the B601 ships as a Damiao and a
        # RobStride arm with the same joint topology and DIFFERENT geometry, and this model
        # is the RobStride one. A Damiao arm has no profile here rather than a near-fit.
        name="rebot_devarm_rs",
        label="reBot DevArm (RobStride)",
        scene=_rebot_devarm_rs_scene,
        # The two gripper slides (joint_left/joint_right, one rack and pinion) are held at
        # their authored pose, not addressed -- see SceneTwin._read_joint_map.
        joints=("joint1", "joint2", "joint3", "joint4", "joint5", "joint6"),
        q_home=Q_HOME_REBOT,
        base_body="base_link",
        gripper_body="gripper_end",
        # This arm's own gripper, not the SO-101 leader's: the reBot has no leader, so
        # showing one put a different robot's tool in the operator's hand.
        ghost=REBOT_GHOST,
        # Solved against Q_HOME_REBOT so this arm demands the wrist the SO-101 does, to
        # 1e-6 deg. Five degrees off the SO-101's, absorbing the pitch this arm's park
        # pose puts on its gripper.
        euler_hand_from_ghost_deg=(-85.0, 0.0, 90.0),
        # Menagerie's model declares no sites, so the frame is given here.
        #
        # The point is this arm's own: measured off the compiled finger meshes, the jaws
        # run out to -88.6 mm along gripper_end's -X.
        #
        # The turn is gripperframe's own rotation off the SO-101's gripper body, reused
        # rather than rederived from these meshes. Its only consumer is the facing (+Z)
        # that sets the base-yaw bias, which the clutch measures at every engage, so what
        # matters is that it is a fixed, non-vertical direction on the tool -- deriving one
        # from these meshes puts it near vertical, where the yaw it feeds is degenerate.
        tool=(
            "gripper_end",
            np.array([-0.0886, 0.0, 0.0]),
            np.array([0.70710678, 0.0, 0.70710678, 0.0]),
        ),
    ),
)

#: The arms a session can preview. ``robot_viz --arm`` and LeRobot's ``RobotProfile`` both
#: select by these keys.
PREVIEW_ARMS: dict[str, PreviewArmProfile] = {p.name: p for p in _PROFILES}

# Where the home gripper sits relative to the operator's head, in XR axes: 0.30 m below eye
# level and 0.60 m ahead on the head's yaw-projected facing (anchor_from_head). Measured
# from the head, not the reference-space origin, which a stage-origin space puts a standing
# height out. A starting pose only: the controller owns position and yaw from the first
# frame carrying one.
HOME_GRIP_FROM_HEAD_XR = np.array([0.0, -0.30, -0.60])

# Where the gripper's jaw sits relative to the controller, in metres, XR axes: level with
# the hand laterally, 0.25 m ahead and 0.10 m below it (XR is y-up and -z-forward,
# viz.robot.frames). Only the starting value for the horizontal pair, which the thumbstick
# walks; the vertical term is fixed. Carried on the controller's own facing.
GRIP_FROM_CONTROLLER_XR = np.array([0.0, -0.10, -0.25])

# What the thumbstick does to the two horizontal terms above. Deflection is a rate, so the
# offset holds where the stick left it: metres per second at full deflection, scaled by the
# frame dt -- not per frame, or its feel would track the frame rate.
_TUNE_RATE_M_S = 0.50
# Sticks drift and the offset is latched, so a resting controller would walk the arm
# away over a session.
_STICK_DEADZONE = 0.15
# Each tuned term, absolutely: a stuck stick must not push the arm out of sight. The
# vertical term is not tuned, so it is not bounded.
_TUNE_LIMIT_M = 1.00

#: The twin's name for every geom on the arm, declared at construction.
FOLLOWER_GROUP = "follower"

# Engageable. The blocked colour is authored in follower_arm.xml: neutral grey, darker at
# 0.45 against this one's 0.68 luminance, so brightness carries the signal as well as hue.
# A translucent arm dilutes both, so check the pair on a headset.
_ENGAGEABLE_RGB = (0.20, 0.85, 0.35)


class PreviewArm:
    """One arm in one scene: posed once, drawn, and driven rigidly by the hand.

    :meth:`drive` moves it two independent ways: position from the controller plus a
    thumbstick-trimmed offset, yaw from the wrist. Placed by the profile's tool frame, so
    the yaw turns about the jaw, not the gripper body behind it.
    """

    def __init__(self, twin, profile: PreviewArmProfile | None = None) -> None:
        """Resolve the arm in ``twin``, pose it at the profile's ``q_home``, and hide it.
        Every geometric constant is measured here; the arm is rigid below ``q_home``.
        """
        self._twin = twin
        self._profile = profile if profile is not None else PREVIEW_ARMS["so101"]
        profile = self._profile
        self._hand_from_ghost = quat_hand_from_ghost(profile.euler_hand_from_ghost_deg)

        included = (
            "It must <include> the profile's own arm wrapper rather than "
            "upstream's MJCF directly."
        )
        # The follower must be the scene's only jointed body, in upstream's order, so a
        # second one fails here rather than landing q_home on somebody else's joints.
        twin.joints.require(profile.joints)

        # Upstream numbers its visual geoms 2 and its collision geoms 3; declare_group
        # raises on an empty set, so a renumbering is an error, not an invisible arm.
        twin.declare_group(FOLLOWER_GROUP, body=profile.base_body, drawn_only=True)
        # One material for every upstream one, so the arm recolours in one write.
        self._blocked_rgba = twin.declare_material(FOLLOWER_MATERIAL, hint=included)
        twin.repaint(FOLLOWER_GROUP, FOLLOWER_MATERIAL)

        # The one and only joint write. Everything after this moves the base.
        twin.home(profile.q_home)

        # The anchor composes its yaw onto the authored base quat rather than replacing
        # it, so a scene that authors a base tilt keeps it.
        self._base_pos, self._authored_base_quat = twin.body_offset(
            profile.base_body, relative_to=WORLD_BODY
        )
        self._base_quat = self._authored_base_quat.copy()

        # The two constants q_home freezes, both in the base's own frame. Composing the
        # base's pose with them replaces every per-frame forward-kinematics read.
        jaw_pos, jaw_quat = self._tool_offset()
        self._jaw_from_base_local = jaw_pos
        # The tool frame's +Z is the direction the jaw faces; its +X is the tool axis.
        self._jaw_facing_local = rotate(np.array([0.0, 0.0, 1.0]), jaw_quat)
        self._gripper_from_base_local = twin.body_offset(
            profile.gripper_body, relative_to=profile.base_body
        )

        # The live grip offset. This class is its only definition; app.py passes two raw
        # stick axes and never learns which way either points.
        self._grip_from_controller_xr = GRIP_FROM_CONTROLLER_XR.copy()
        # Set while the stick is moving the offset, so it is logged once on the release.
        self._tuning = False

        self._anchored = False
        # The yaw the base is currently turned by -- the wrist's, past the first driven
        # frame, and so not the operator's above.
        self._base_yaw_xr = np.array([1.0, 0.0, 0.0, 0.0])
        self.set_visible(False)

    def _tool_offset(self) -> tuple[np.ndarray, np.ndarray]:
        """The tool frame in the base's own frame, from a site or a body-plus-offset."""
        tool = self._profile.tool
        base = self._profile.base_body
        if isinstance(tool, str):
            return self._twin.site_offset(tool, relative_to=base)
        body, offset, turn = tool
        pos, quat = self._twin.body_offset(body, relative_to=base)
        return pos + rotate(np.asarray(offset, dtype=float), quat), multiply(quat, turn)

    # ---------------------------------------------------------------- geometry

    @property
    def name(self) -> str:
        """Which arm this is previewing, by profile key."""
        return self._profile.name

    @property
    def ghost(self) -> GhostSpec:
        """The gripper this arm puts on the hand."""
        return self._profile.ghost

    @property
    def hand_from_ghost(self) -> np.ndarray:
        """This arm's ghost calibration, for :mod:`.so101_ghost`'s conversions."""
        return self._hand_from_ghost

    @property
    def anchored(self) -> bool:
        """Whether a head pose has placed the arm; False after :meth:`unanchor`."""
        return self._anchored

    def unanchor(self) -> None:
        """Drop the anchor so the next head pose re-places the arm. For a runtime
        recentre: the old frame was taken off a head pose in the old reference space.
        """
        self._anchored = False

    @property
    def base_yaw_xr(self) -> np.ndarray:
        """The XR yaw (wxyz) the base is turned by; the wrist's past the first driven
        frame, and identity before any.
        """
        return self._base_yaw_xr.copy()

    def anchor(self, head_pose_xr: np.ndarray) -> np.ndarray:
        """Take the offset's frame off the first head pose, park the arm, and return the
        XR home grip. The controller owns position and yaw from the first driven frame."""
        home_xr, q_yaw_xr = anchor_from_head(head_pose_xr, HOME_GRIP_FROM_HEAD_XR)
        self._anchored = True
        self._place(home_xr, q_yaw_xr)
        LOG.info(
            "preview arm: anchored to a head at XR (%.2f, %.2f, %.2f) facing %.0f deg; "
            "home grip at XR (%.2f, %.2f, %.2f), base at MuJoCo (%.3f, %.3f, %.3f). "
            "The controller owns both from the first driven frame.",
            *np.asarray(head_pose_xr, dtype=float)[:3],
            math.degrees(2.0 * math.atan2(q_yaw_xr[2], q_yaw_xr[0])),
            *home_xr,
            *self._base_pos,
        )
        return home_xr

    def reset_offset(self) -> None:
        """Put the grip offset back to :data:`GRIP_FROM_CONTROLLER_XR`. Any phase."""
        self._grip_from_controller_xr = GRIP_FROM_CONTROLLER_XR.copy()
        self._tuning = False

    def _place(self, grip_xr: np.ndarray, q_yaw_xr: np.ndarray) -> None:
        """Turn the base onto a yaw and put the jaw on an XR point. Does both, always:
        turning the base swings the jaw around it. One publish, both fields.
        """
        # Yaw on the left: it turns the arm in the world, where upstream's quat orients it
        # in its own frame. Upstream authors identity, so no shipped scene can tell the two
        # orders apart -- this comment is the only guard.
        turned = multiply(
            frames.mj_from_xr_rotation(q_yaw_xr), self._authored_base_quat
        )
        self._base_quat = turned
        self._base_yaw_xr = np.asarray(q_yaw_xr, dtype=float).copy()
        self._base_pos = (
            np.array(frames.mj_from_xr_pos(list(grip_xr)), dtype=float)
            - self.jaw_from_base
        )
        self._twin.publish(
            bodies={self._profile.base_body: (self._base_pos, self._base_quat)}
        )

    @property
    def jaw_from_base(self) -> np.ndarray:
        """Base origin -> the jaw tool frame, in MuJoCo world axes: the load-time
        constant turned by the base's current orientation.
        """
        return rotate(self._jaw_from_base_local, self._base_quat)

    @property
    def jaw_yaw_xr(self) -> np.ndarray:
        """The XR yaw (wxyz) the jaw faces along: the tool frame's +Z. Not the
        links' reach -- J5 rolls the jaw about the tool axis without moving them.
        """
        facing = rotate(self._jaw_facing_local, self._base_quat)
        inverse = conjugate(np.array(frames.QUAT_MJ_FROM_XR, dtype=float))
        facing_xr = rotate(facing, inverse)
        return yaw_of_direction(facing_xr, np.array([0.0, 0.0, -1.0]))

    def gripper_pose_mj(self) -> tuple[np.ndarray, np.ndarray]:
        """The gripper body's ``(pos, quat_wxyz)`` in MuJoCo world coordinates. The
        position sits 98.4 mm short of the jaw, so do not read it as the tool point.
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

        Both yaws arrive already computed, because deriving them needs the grip calibration
        this module does not get to learn: ``q_facing_xr`` is where the controller points,
        ``q_base_yaw_xr`` what to turn the base onto, and they differ by app.py's measured
        bias. Only legal once :attr:`anchored` and while DISENGAGED -- an offset moving
        while the arm is frozen applies its excursion on the release frame.
        """
        self._walk(stick_x, stick_y, dt)
        # The controller's facing, not the base yaw, which leads it by the bias and would
        # send "forward" off by that much. A yaw leaves the vertical term untouched, so this
        # one rotate is correct for all three.
        offset = rotate(self._grip_from_controller_xr, q_facing_xr)
        self._place(np.asarray(hand_pos_xr, dtype=float) + offset, q_base_yaw_xr)

    @property
    def grip_from_controller_xr(self) -> np.ndarray:
        """The live gripper-from-controller offset in XR axes, tuning included."""
        return self._grip_from_controller_xr.copy()

    def _walk(self, stick_x: float, stick_y: float, dt: float) -> None:
        """Walk the offset's two horizontal terms at the thumbstick's deflection. OpenXR's
        stick is +x right and +y forward while XR is -z forward, so z opposes the stick.
        """
        step = _TUNE_RATE_M_S * float(dt)
        delta = np.array([deflection(stick_x) * step, 0.0, -deflection(stick_y) * step])
        if not delta.any():
            if self._tuning:
                self._tuning = False
                # In the constant's own form, so a headset session ends in a value that
                # can be pasted back into this file.
                LOG.info(
                    "preview arm: offset tuned to GRIP_FROM_CONTROLLER_XR = "
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
        """Draw the arm, or not; never while un-anchored, since drawing it against the
        reference-space origin is the bug the anchor exists to fix.
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
            "preview arm: %s home grip %.2f m below and %.2f m in front of the HEAD, "
            "turned onto its facing, on the first frame carrying one. Hidden until then. "
            "After it: the JAW dragged rigidly by the controller at (%.2f, %.2f, %.2f) "
            "off it, turning about itself on the wrist's own yaw, with the right "
            "thumbstick trimming the horizontal pair to +-%.2f m.",
            self._profile.label,
            -HOME_GRIP_FROM_HEAD_XR[1],
            -HOME_GRIP_FROM_HEAD_XR[2],
            *GRIP_FROM_CONTROLLER_XR,
            _TUNE_LIMIT_M,
        )


def deflection(axis: float) -> float:
    """One stick axis past the deadzone, or zero inside it. Spelled ``not >=`` so a
    non-finite axis falls inside; everything the stick drives is latched.
    """
    value = float(axis)
    return 0.0 if not abs(value) >= _STICK_DEADZONE else value
