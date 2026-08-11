# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The ghost catalogue: one entry per ``--robot`` value.

Everything a gripper ghost needs that is not shared machinery -- its scene, its
fetched meshes, its mocap bodies, how each moving part is driven by one
closedness scalar, and where it sits on the operator's hand. app.py holds the
machinery and reads it from here, so adding a robot is a new ``Robot`` and its
two authored files (a scene and a mesh wrapper) rather than a branch in the
frame loop.

Both ghosts are driven by ONE scalar in ``[0, 1]``: 0 released, 1 squeezed. A
part is a hinge (a lever swinging about a pivot) or a slide (a jaw translating
along an axis); those two cases are the whole of ``app._update_ghost``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import mujoco
import numpy as np

# Package data, so paths resolve identically from the wheel and the source tree.
# Must stay absolute: a scene <include>s a fragment in a subdirectory, and on
# mujoco 3.11.0 a relative model path mis-composes that fragment's mesh paths
# and fails naming a file that is right there on disk.
_ASSETS = Path(__file__).parent / "assets"


class PartKind(StrEnum):
    """The two ways one closedness scalar can move a part.

    These are the whole of ``app._update_ghost``. A third would need a branch
    there, which is what ``test_every_robot_declares_its_own_assets`` guards by
    enumerating the members a robot is allowed to use.
    """

    HINGE = "hinge"
    """A lever swinging about a pivot; the value is an angle in radians."""
    SLIDE = "slide"
    """A jaw translating along an axis; the value is a displacement in metres."""


def quat_from_euler_deg(angles_deg) -> np.ndarray:
    """Intrinsic X-then-Y-then-Z degrees -> a wxyz quaternion.

    Right-multiplication is what makes it intrinsic, and is the convention
    MuJoCo's `euler=` uses. Spelled out rather than calling mju_euler2Quat so
    the sequence is visible at the point of use.
    """
    quat = np.array((1.0, 0.0, 0.0, 0.0))
    for axis, angle in zip(np.eye(3), angles_deg):
        step = np.empty(4)
        mujoco.mju_axisAngle2Quat(step, axis, math.radians(angle))
        composed = np.empty(4)
        mujoco.mju_mulQuat(composed, quat, step)
        quat = composed
    return quat


@dataclass(frozen=True)
class Part:
    """One moving mocap body, driven from closedness by a single scalar.

    ``released`` / ``squeezed`` are the joint values at closedness 0 and 1, in
    the unit ``kind`` names. Both are expressed in the ghost root's frame, and
    every part's XML rest pose equals the root's, so a pivot lives in exactly one
    place (see the ghost fragments).
    """

    body: str
    kind: PartKind
    axis: np.ndarray
    released: float
    squeezed: float
    # Hinge only; a slide has no pivot and leaves this None.
    pivot: np.ndarray | None = None


@dataclass(frozen=True)
class Robot:
    """One selectable ghost."""

    key: str
    description: str
    scene: Path
    assets: Path
    meshes: tuple[str, ...]
    fetch_script: str
    body: str
    parts: tuple[Part, ...]
    # How the ghost sits on the hand. `pos` is in the GRIP frame and `quat`
    # right-multiplies the grip orientation; see app._update_ghost.
    pos_grip_from_ghost: np.ndarray
    quat_grip_from_ghost: np.ndarray
    # What drives the jaw, for the startup log. The node itself is shared.
    drive: str

    def missing_meshes(self) -> list[str]:
        """Names of the fetched meshes that are not on disk. Empty when fetched."""
        return [n for n in self.meshes if not (self.assets / n).is_file()]


# ── SO-101 leader gripper ──────────────────────────────────────────────────
# The handheld leader device itself, so the ghost is the tool the operator's
# fist is actually closed around.
#
# The trigger hinge is the follower's `gripper` revolute joint, from SO-ARM100's
# so101_new_calib.urdf: origin xyz="0.0202 0.0188 -0.0234" rpy="1.5708 0 0",
# axis "0 0 1". The right source even for the LEADER's trigger, which is mounted
# in the follower's moving-jaw slot and shares the hinge. The axis below is that
# "0 0 1" carried through the joint frame's 90-degree roll.
#
# Do not re-derive either from the meshes: a pivot from the nearest
# trigger-to-shank vertex pair and an axis from the grip frame both look right at
# the joint's zero and are wrong by the far end of its travel.
#
# The travel is the URDF joint's own: `upper="1.74533"` is 100.0 degrees, and
# squeezed is its authored zero. A released end short of that does not read as an
# OPEN gripper on a headset, which is the only place this can be judged. Do not
# extend to the joint's lower limit (-10 deg): that end swings the lever 0.4 mm
# into the servo. The tightest pass across 0..100 is 2.1 mm, at the squeezed end.
_SO101_TRIGGER = Part(
    body="leader_ghost_jaw",
    kind=PartKind.HINGE,
    axis=np.array((0.0, -1.0, 0.0)),
    pivot=np.array((0.0202, 0.0188, -0.0234)),  # metres, ghost frame
    released=math.radians(100.0),  # closedness 0, jaw wide open
    squeezed=0.0,  # closedness 1, tucked to the authored pose
)

# Where the ghost sits on the hand. MEASURED ON A HEADSET, not derived: this is
# a claim about a hand holding a CONTROLLER, so do not re-derive it from the
# mesh -- a model assuming the hand passes through the handle loop puts the loop
# centroid 56 mm from the palm.
#
# Euler degrees, intrinsic XYZ, i.e. MuJoCo's `euler=` and NOT URDF's rpy. To
# re-tune, change one angle and reinstall: Rz spins the gripper about its long
# axis, Rx/Ry tilt it, the position slides it along the grip axes. No test
# asserts a posture, so re-tuning cannot turn them red.
SO101_EULER_GRIP_FROM_GHOST_DEG = (60, 180, 270)

SO101 = Robot(
    key="so101",
    description="SO-101 leader gripper",
    scene=_ASSETS / "so101_scene.xml",
    assets=_ASSETS / "leader",
    meshes=(
        "Wrist_Roll_SO101.stl",
        "Trigger_SO101.stl",
        "Handle_SO101.stl",
        "STS3215_03a.stl",
    ),
    fetch_script="examples/mujoco_xr/scripts/fetch-so-arm.sh",
    body="leader_ghost",
    parts=(_SO101_TRIGGER,),
    pos_grip_from_ghost=np.array((0.0, 0.02, -0.025)),
    quat_grip_from_ghost=quat_from_euler_deg(SO101_EULER_GRIP_FROM_GHOST_DEG),
    drive="trigger hinge, 100 deg released to 0 deg squeezed",
)


# ── reBot DevArm gripper ───────────────────────────────────────────────────
# The FOLLOWER's parallel jaw, not a leader handle: the reBot leader is a
# back-driven arm on a table, so what the controller commands is this. Two jaws
# on one rack, so both parts read the same closedness and travel together.
#
# From Seeed's own 00-arm-rs_asm-v3.urdf. joint_left / joint_right sit at
# xyz="-0.041939 -+7.3385e-05 0" with rpy="+-1.5708 -1.5708 0" and axis "0 0 1",
# which carries to -+y in the gripper_end frame -- so positive travel SEPARATES
# the jaws and the joints' authored zero is the CLOSED end (fingertips 0.15 mm
# apart). That is the opposite polarity to the SO-101 trigger above.
#
# Travel is joint_left's `upper="0.05"`, taken for BOTH jaws. Upstream disagrees
# with itself -- joint_right says 0.0715 for the same rack-driven pair -- and
# 0.05 is the one the geometry supports: at 0.05 the carriage's outer edge stops
# 3.4 mm inside the end of the cnc7 rail plate, and at 0.0715 it hangs 18.1 mm
# past it. 0.05 per jaw is a 100 mm opening.
_REBOT_TRAVEL_M = 0.05
_REBOT_JAWS = tuple(
    Part(
        body=f"rebot_ghost_{side}",
        kind=PartKind.SLIDE,
        axis=np.array((0.0, sign, 0.0)),
        released=_REBOT_TRAVEL_M,  # closedness 0, jaws wide open
        squeezed=0.0,  # closedness 1, fingertips together
    )
    for side, sign in (("left", -1.0), ("right", 1.0))
)

# A CONVENTION, not a headset measurement, and that is the difference from the
# SO-101 above: nobody holds this gripper, so there is no fist-on-a-handle claim
# to measure. It is placed by the OpenXR grip frame's own definition -- +X into
# the palm, -Z forward through the tube-shaped fist (where a pen tip would
# point), +Y out of the fist toward the thumb:
#
#   ghost +x (the approach axis, jaws reaching forward) -> grip -Z
#   ghost +-y (the jaw opening axis)                    -> grip +-X, so the jaws
#                                                          open the way the index
#                                                          finger squeezes
#
# which is exactly Rx(90) Ry(0) Rz(270).
REBOT_EULER_GRIP_FROM_GHOST_DEG = (90, 0, 270)

# Slides the fist onto the gripper's drive motor rather than onto the link
# origin, which is out at the fingertips. Derived: motor_7 spans x in
# [-0.1572, -0.0927] in the ghost frame, so its centre is at -0.125, and
# Rz(270)-through-Rx(90) carries a ghost +x offset onto grip -Z.
REBOT_POS_GRIP_FROM_GHOST = np.array((0.0, 0.0, -0.125))

REBOT = Robot(
    key="rebot",
    description="reBot DevArm gripper",
    scene=_ASSETS / "rebot_scene.xml",
    assets=_ASSETS / "rebot",
    meshes=(
        "pla7_green.STL",
        "cnc7.STL",
        "motor_7.STL",
        "pla_left.STL",
        "cnc_left.STL",
        "pla_right.STL",
        "cnc_right.STL",
    ),
    fetch_script="examples/mujoco_xr/scripts/fetch-rebot-arm.sh",
    body="rebot_ghost",
    parts=_REBOT_JAWS,
    pos_grip_from_ghost=REBOT_POS_GRIP_FROM_GHOST,
    quat_grip_from_ghost=quat_from_euler_deg(REBOT_EULER_GRIP_FROM_GHOST_DEG),
    drive=f"two rack-driven jaws, {_REBOT_TRAVEL_M * 2000:.0f} mm open to closed",
)


ROBOTS = {robot.key: robot for robot in (SO101, REBOT)}
DEFAULT_ROBOT = SO101.key
