# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The SO-101 leader gripper locked to the operator's hand, and the frame algebra for it.

Two mocap bodies -- the gripper and its trigger, which articulates -- placed from a 7-D XR
hand pose. The grip calibration lives on this side of the boundary so :mod:`.preview_arm`
never learns it.

:func:`ghost_body_from_pose` and :func:`pose_from_ghost_body` are exact inverses, which is
what makes the engage handoff exact, and is also the trap: the calibration cancels through
that handoff, so every geometric test passes for any value of it. Its one surviving effect
is which wrist posture the engage gate demands.
"""

from __future__ import annotations

import math

import numpy as np

from . import frames
from .ghost import GhostHinge, GhostSpec
from .quaternion import conjugate, from_axis_angle, multiply, rotate, to_matrix

# The two mocap bodies leader_gripper.xml declares.
GHOST_BODY = "leader_ghost"
GHOST_JAW_BODY = "leader_ghost_jaw"


# Where the ghost sits on the hand, for an arm that names no calibration of its own. Euler
# degrees, intrinsic XYZ, i.e. MuJoCo's `euler=`. It pairs with one q_home and no other: it
# is what turns that pose's gripper orientation into the hand the gate demands, so moving
# q_home without re-solving this rotates that demand by the same amount. Each preview arm
# carries its own (PreviewArmProfile.euler_hand_from_ghost_deg); this is the SO-101's, kept
# as the default so the functions below can still be called bare.
#
# Re-solve it against the arm's own q_home, never by eye, and compare in the OPERATOR's
# frame (log_grip_posture's second number) -- the absolute demanded quaternion moves with
# any roll about the tool axis while the wrist the operator must actually hold does not,
# so matching the absolute one "preserves" a quantity nobody feels. Do not port a
# grip-measured value, which demands a wrist pitch nobody chose.
EULER_HAND_FROM_GHOST_DEG = (270, 0, 90)
# Measured on a headset: a claim about a hand holding a CONTROLLER, so do not re-derive
# it from the mesh. Relative to HAND_POSE; `_log_hand_frames` prints the replacement
# when that changes.
POS_HAND_FROM_GHOST = np.array((0, 0, 0))

# The trigger hinge: the follower's `gripper` revolute joint, from SO-ARM100's
# so101_new_calib.urdf (origin xyz="0.0202 0.0188 -0.0234" rpy="1.5708 0 0", axis "0 0 1"),
# whose moving-jaw slot the leader's trigger shares. The axis below is that "0 0 1" carried
# through the joint frame's 90-degree roll. Do not re-derive either from the meshes: both
# look right at the joint's zero and are wrong by the far end of its travel.
_TRIGGER_HINGE_POS = np.array((0.0202, 0.0188, -0.0234))  # metres, ghost frame
_TRIGGER_HINGE_AXIS = np.array((0.0, -1.0, 0.0))  # unit, ghost frame

# The travel is the URDF joint's own: `upper="1.74533"` is 100.0 degrees and squeezed is
# its authored zero. Do not extend to the joint's lower limit (-10 deg): that end swings
# the lever 0.4 mm into the servo.
TRIGGER_RELEASED_RAD = math.radians(100.0)  # closedness 0, jaw wide open
TRIGGER_SQUEEZED_RAD = 0.0  # closedness 1, tucked to the authored pose


def _quat_from_euler_deg(angles_deg) -> np.ndarray:
    """Intrinsic X-then-Y-then-Z degrees -> a wxyz quaternion, MuJoCo's `euler=`.
    Right-multiplication is what makes it intrinsic.
    """
    quat = np.array((1.0, 0.0, 0.0, 0.0))
    for axis, angle in zip(np.eye(3), angles_deg):
        step = from_axis_angle(axis, math.radians(angle))
        composed = multiply(quat, step)
        quat = composed
    return quat


# Derived; nothing from here on is authored.
_QUAT_HAND_FROM_GHOST = _quat_from_euler_deg(EULER_HAND_FROM_GHOST_DEG)


def quat_hand_from_ghost(euler_deg) -> np.ndarray:
    """One arm's calibration as a quaternion, from its ``euler_deg``."""
    return _quat_from_euler_deg(euler_deg)


def _resolve(hand_from_ghost: np.ndarray | None) -> np.ndarray:
    return _QUAT_HAND_FROM_GHOST if hand_from_ghost is None else hand_from_ghost


def ghost_body_from_pose(
    pose: np.ndarray, hand_from_ghost: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """A 7-D XR hand pose -> where the leader ghost body goes in MuJoCo world.

    ``hand_from_ghost`` is the arm's own calibration, defaulting to the SO-101's. It
    right-multiplies because it is fixed in the gripper's frame; left-multiplying swings the
    ghost around the room as the operator turns.
    """
    p_xr = [float(pose[0]), float(pose[1]), float(pose[2])]
    q_xyzw = [float(pose[3]), float(pose[4]), float(pose[5]), float(pose[6])]

    q_grip = np.array(frames.mj_from_xr_quat(q_xyzw), dtype=float)
    p_grip = np.array(frames.mj_from_xr_pos(p_xr), dtype=float)

    q_body = multiply(q_grip, _resolve(hand_from_ghost))
    p_offset = rotate(POS_HAND_FROM_GHOST, q_grip)
    return p_grip + p_offset, q_body


def _grip_quat_mj(
    q_body: np.ndarray, hand_from_ghost: np.ndarray | None = None
) -> np.ndarray:
    """The MuJoCo grip orientation (wxyz) whose ghost body lands at ``q_body``."""
    inverse = conjugate(_resolve(hand_from_ghost))
    q_grip = multiply(np.asarray(q_body, dtype=float), inverse)
    return q_grip


def grip_quat_from_ghost_body(
    q_body: np.ndarray, hand_from_ghost: np.ndarray | None = None
) -> np.ndarray:
    """The XR hand orientation (xyzw) that would put the ghost body at ``q_body``.

    The engage gate's second operand. Both operands are xyzw in XR, which is what makes a
    geodesic angle meaningful.
    """
    return frames.xr_from_mj_quat(_grip_quat_mj(q_body, hand_from_ghost))


def pose_from_ghost_body(
    p_body: np.ndarray, q_body: np.ndarray, hand_from_ghost: np.ndarray | None = None
) -> np.ndarray:
    """The exact inverse of :func:`ghost_body_from_pose`, as a 4x4 in the XR frame.

    4x4 for ``SO101ClutchRetargeter.set_home_base_T_ee``, and XR because the app does no
    rebase, so "base" is the XR anchor.
    """
    q_grip = _grip_quat_mj(q_body, hand_from_ghost)
    p_offset = rotate(POS_HAND_FROM_GHOST, q_grip)

    transform = np.eye(4)
    transform[:3, 3] = frames.xr_from_mj_pos(np.asarray(p_body, dtype=float) - p_offset)
    q_xyzw = frames.xr_from_mj_quat(q_grip)
    transform[:3, :3] = to_matrix(
        np.array([q_xyzw[3], q_xyzw[0], q_xyzw[1], q_xyzw[2]])
    )
    return transform


# Handle centroid to wrist-roll centroid in the ghost body frame, measured on the fetched
# meshes: (-56.9, -0.5, -63.2) mm -> (-4.3, -1.4, -13.2) mm. Rotated by the follower
# `gripper` quaternion, since the handoff puts the ghost body on its orientation exactly.
GHOST_POINTING_AXIS = np.array((0.7228, -0.0124, 0.6910))


#: The SO-101's: its LEADER's gripper, whose trigger shares the follower's moving-jaw slot.
SO101_GHOST = GhostSpec(
    body=GHOST_BODY,
    geoms=(
        "leader_ghost_wrist_roll",
        "leader_ghost_motor",
        "leader_ghost_handle",
        "leader_ghost_trigger",
    ),
    jaw=(
        GhostHinge(
            body=GHOST_JAW_BODY,
            pivot=_TRIGGER_HINGE_POS,
            axis=_TRIGGER_HINGE_AXIS,
            released_rad=TRIGGER_RELEASED_RAD,
            squeezed_rad=TRIGGER_SQUEEZED_RAD,
        ),
    ),
)
