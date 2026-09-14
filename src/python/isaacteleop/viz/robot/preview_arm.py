# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The SO-101 arm the operator drags by hand before the clutch engages.

The joints are written once, to :data:`Q_HOME`, and the arm is moved as a rigid body:
:meth:`PreviewArm._place` is the one place its base pose is published, and every other
frame on the arm is that pose composed with a constant measured at :data:`Q_HOME`. This
module must not learn the leader ghost's grip calibration, which is a claim about a hand
holding a controller; :mod:`.so101_ghost` converts between the two.
"""

from __future__ import annotations

import logging
import math

import numpy as np

from . import frames
from .anchor import anchor_from_head, yaw_of_direction
from .quaternion import conjugate, multiply, rotate
from .scene import WORLD_BODY

LOG = logging.getLogger(__name__)

# Declared by assets/follower_arm.xml and repointed onto every follower geom
# at startup, so the arm recolours in one write.
FOLLOWER_MATERIAL = "follower_arm"

BASE_BODY = "base"
GRIPPER_BODY = "gripper"

# Upstream's own tool frame, declared on the `gripper` body 98.4 mm out from its origin
# and 3.8 mm off the closed jaw surface. The arm is placed by this point, so it is also the
# axis the yaw turns about; placing by the gripper body instead swings the jaw on a 15.8 mm
# arc across +-90 degrees of yaw.
GRIPPER_SITE = "gripperframe"

# Upstream's joint order, which is also the qpos order Q_HOME is written in. Asserted by
# name at startup: a reordered upstream file would land Q_HOME's angles on the wrong
# joints and still look like an arm.
ARM_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
)
GRIPPER_JOINT = "gripper"

# The configuration the arm holds for the whole session, written to qpos once at
# construction. This pose is the wrist posture the engage gate demands, so re-solve
# _EULER_HAND_FROM_GHOST_DEG whenever it changes. J4 stops at +-95 degrees.
Q_HOME_DEG = (
    0.00,  # J1 shoulder_pan  -- base yaw
    -45.00,  # J2 shoulder_lift -- first segment elevation
    45.00,  # J3 elbow_flex    -- second segment elevation
    90.00,  # J4 wrist_flex    -- wrist up/down
    -90.00,  # J5 wrist_roll    -- spin about the tool axis
    00.00,  # J6 gripper       -- jaw opening, 0 is the authored pose
)
Q_HOME = np.radians(Q_HOME_DEG)

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
_TUNE_RATE_M_S = 0.20
# Sticks drift and the offset is latched, so a resting controller would walk the arm
# away over a session.
_STICK_DEADZONE = 0.15
# Each tuned term, absolutely: a stuck stick must not push the arm out of sight. The
# vertical term is not tuned, so it is not bounded.
_TUNE_LIMIT_M = 0.60

#: The twin's name for every geom on the arm, declared at construction.
FOLLOWER_GROUP = "follower"

# Engageable. The blocked colour is authored in follower_arm.xml: neutral grey, darker at
# 0.45 against this one's 0.68 luminance, so brightness carries the signal as well as hue.
# A translucent arm dilutes both, so check the pair on a headset.
_ENGAGEABLE_RGB = (0.20, 0.85, 0.35)


class PreviewArm:
    """The SO-101 in one scene: posed once, drawn, and driven rigidly by the hand.

    :meth:`drive` moves it two independent ways: position from the controller plus a
    thumbstick-trimmed offset, yaw from the wrist. Placed by :data:`GRIPPER_SITE`, so the
    yaw turns about the jaw; the gripper body sits 98.4 mm short of it.
    """

    def __init__(self, twin) -> None:
        """Resolve the arm in ``twin``, pose it at :data:`Q_HOME`, and hide it. Every
        geometric constant is measured here; the arm is rigid below Q_HOME.
        """
        self._twin = twin

        included = (
            "It must <include> assets/follower_arm.xml rather than "
            "upstream's MJCF directly."
        )
        # The follower must be the scene's only jointed body, in upstream's order, so a
        # second one fails here rather than landing Q_HOME on somebody else's joints.
        twin.joints.require(ARM_JOINTS + (GRIPPER_JOINT,))

        # Upstream numbers its visual geoms 2 and its collision geoms 3; declare_group
        # raises on an empty set, so a renumbering is an error, not an invisible arm.
        twin.declare_group(FOLLOWER_GROUP, body=BASE_BODY, drawn_only=True)
        # One material for thirteen upstream ones, so the arm recolours in one write.
        self._blocked_rgba = twin.declare_material(FOLLOWER_MATERIAL, hint=included)
        twin.repaint(FOLLOWER_GROUP, FOLLOWER_MATERIAL)

        # The one and only joint write. Everything after this moves the base.
        twin.home(Q_HOME)

        # The anchor composes its yaw onto the authored base quat rather than replacing
        # it, so a scene that authors a base tilt keeps it.
        self._base_pos, self._authored_base_quat = twin.body_offset(
            BASE_BODY, relative_to=WORLD_BODY
        )
        self._base_quat = self._authored_base_quat.copy()

        # The two constants Q_HOME freezes, both in the base's own frame. Composing the
        # base's pose with them replaces every per-frame forward-kinematics read.
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
        # Set while the stick is moving the offset, so it is logged once on the release.
        self._tuning = False

        self._anchored = False
        # The yaw the base is currently turned by -- the wrist's, past the first driven
        # frame, and so not the operator's above.
        self._base_yaw_xr = np.array([1.0, 0.0, 0.0, 0.0])
        self.set_visible(False)

    # ---------------------------------------------------------------- geometry

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
        self._twin.publish(bodies={BASE_BODY: (self._base_pos, self._base_quat)})

    @property
    def jaw_from_base(self) -> np.ndarray:
        """Base origin -> the jaw tool frame, in MuJoCo world axes: the load-time
        constant turned by the base's current orientation.
        """
        return rotate(self._jaw_from_base_local, self._base_quat)

    @property
    def jaw_yaw_xr(self) -> np.ndarray:
        """The XR yaw (wxyz) the jaw faces along: :data:`GRIPPER_SITE`'s +Z. Not the
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
            "preview arm: SO-101 home grip %.2f m below and %.2f m in front of the HEAD, "
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
    """One stick axis past the deadzone, or zero inside it. Spelled ``not >=`` so a
    non-finite axis falls inside; everything the stick drives is latched.
    """
    value = float(axis)
    return 0.0 if not abs(value) >= _STICK_DEADZONE else value
