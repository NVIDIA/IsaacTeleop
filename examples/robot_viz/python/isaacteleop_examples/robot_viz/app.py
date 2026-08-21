# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A MuJoCo scene drawn into a Televiz XR session.

TeleopSession owns both halves: it creates the OpenXR session the trackers and the
compositor share, and runs the twin's frame loop on its own thread.

    TeleopSession ──┬── DeviceIOSession ── trackers ── the retargeting graph
                    │                                          │
                    └── render thread ── SceneTwin ◀── publish(...)
                                            │
                                 ProjectionLayer.submit()

This module holds no mjModel and no mjData. It addresses the scene by name and
publishes what moved -- the base's pose, the ghost's two mocap bodies, which group
is drawn, which material is which colour -- and the render thread applies the lot,
runs one mj_forward and draws. See twin.py for that contract and README.md for the
rest of the design.

Two cadences, deliberately: the control loop below is paced off the wall clock and
the render thread off the display. The one thing that crosses back is the head
pose, which anchors the arm once and is read as "where the operator was", never as
a per-frame signal.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import logging
import math
import sys
import time
from pathlib import Path

import numpy as np

from isaacteleop import viz
from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import (
    ExecutionEvents,
    ExecutionState,
    OptionalTensorGroup,
    OutputCombiner,
    TensorGroup,
    ValueInput,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import OptionalType
from isaacteleop.retargeting_engine.tensor_types import (
    BoolFlag,
    ControllerInputIndex,
    HandPose,
    TransformMatrix,
)
from isaacteleop.retargeters.controller_pose_source import ControllerPoseSource
from isaacteleop.retargeters.engage_gate import (
    KEY_ENGAGED,
    EngageAlignmentGate,
    GateVerdict,
)
from isaacteleop.retargeters.rate_limiter import (
    EE_POSE_KEY,
    EePoseRateLimiter,
    RateLimiterConfig,
)
from isaacteleop.retargeters.SO101.clutch_retargeter import SO101ClutchRetargeter
from isaacteleop.retargeters.SO101.gripper_retargeter import (
    GRIPPER_COMMAND_KEY,
    SO101GripperRetargeter,
)
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig
from isaacteleop.teleop_session_manager.config import TwinRenderConfig
from isaacteleop.viz.robot import (
    MIN_QUAT_NORM,
    VIEW_COUNT,
    SceneTwin,
    frames,
    is_unit,
    yaw_of_axis,
)
from isaacteleop.viz.robot.quaternion import (
    conjugate,
    from_axis_angle,
    multiply,
    rotate,
    to_matrix,
)

from . import follower
from .harness import HarnessBand, InterventionMonitor

LOG = logging.getLogger("robot_viz")

# The app's only clip planes. TwinRenderConfig hands the same pair to the compositor
# and to the twin's projection, or world-locked geometry swims under head motion --
# and only a headset shows it. There is no near/far literal in the backend, by construction.
NEAR_Z = 0.05
FAR_Z = 50.0

_CLOCK_SOURCE = (
    "FrameInfo.predicted_display_time; frames with no prediction are skipped, "
    "not sampled as 0"
)

# Package data, so it resolves the same from the wheel and the source tree. Keep it
# ABSOLUTE: on mujoco 3.11.0 a relative model path composes scene.xml's nested
# <include> path onto itself and opens `<dir>/<dir>/so101_new_calib.xml`.
DEFAULT_SCENE = Path(__file__).parent / "assets" / "scene.xml"

# Checked by name before MuJoCo sees the scene: its failure for a missing
# <include> target is a bare "Error opening file <mesh>.stl", naming a file
# nobody asked for.
FETCH_SCRIPT = "examples/robot_viz/scripts/fetch-so-arm.sh"
_ASSETS = Path(__file__).parent / "assets"
_LEADER_ASSETS = _ASSETS / "leader"
_FETCHED = (
    "leader/Wrist_Roll_SO101.stl",
    "leader/Trigger_SO101.stl",
    "leader/Handle_SO101.stl",
    "leader/STS3215_03a.stl",
    "follower/so101_new_calib.xml",
    "follower/base_motor_holder_so101_v1.stl",
    "follower/base_so101_v2.stl",
    "follower/motor_holder_so101_base_v1.stl",
    "follower/motor_holder_so101_wrist_v1.stl",
    "follower/moving_jaw_so101_v1.stl",
    "follower/rotation_pitch_so101_v1.stl",
    "follower/sts3215_03a_no_horn_v1.stl",
    "follower/sts3215_03a_v1.stl",
    "follower/under_arm_so101_v1.stl",
    "follower/upper_arm_so101_v1.stl",
    "follower/waveshare_mounting_plate_so101_v2.stl",
    "follower/wrist_roll_follower_so101_v1.stl",
    "follower/wrist_roll_pitch_so101_v2.stl",
)


def _missing_assets() -> list[str]:
    """The fetched files that are not on disk. Empty when fetched.

    Both tools, because one scene includes both. Hand-kept in step with the ``ASSETS``
    list in ``scripts/fetch-so-arm.sh``: a destination renamed in one and not the other
    makes this demand a file nothing fetches, or miss one the scene needs.
    """
    return [n for n in _FETCHED if not (_ASSETS / n).is_file()]


# One hand and no flag: the ghost is a right-handed gripper.
GHOST_HAND = ControllersSource.RIGHT

# The two mocap bodies leader_gripper.xml declares.
GHOST_BODY = "leader_ghost"
GHOST_JAW_BODY = "leader_ghost_jaw"

# The twin's name for the four ghost geoms, hidden as a set whenever the follower
# is the tool on show.
GHOST_GROUP = "ghost"
GHOST_GEOMS = (
    "leader_ghost_wrist_roll",
    "leader_ghost_motor",
    "leader_ghost_handle",
    "leader_ghost_trigger",
)

# Three pose channels, three jobs, and none substitutes for another. HAND_POSE_KEY is
# Optional and is the app's ONLY tracking-loss oracle; it is what drives the follower
# and the gate's rotation operand. COMMANDED_POSE_KEY is what the limiter was handed,
# the reference its band is measured against; it is required, so it can never signal
# loss. EE_POSE_KEY is the limiter's output and the only channel anything draws.
HAND_POSE_KEY = "hand_pose"
COMMANDED_POSE_KEY = "commanded_ee_pose"

# The one hand frame, reaching the follower's drive, the gate's operand, the clutch's
# home and the ghost. Aim because only aim's -Z is a pointing ray; grip's runs little
# finger to thumb, whose azimuth turns 1:1 with the hand but has an arbitrary zero. The
# cost is aim's device-specific ray origin, which gives the arm's position a lever arm
# as the wrist turns. Everything relative to this frame must be re-derived when it
# changes. See README.md.
HAND_POSE = HandPose.AIM

# The B button. ControllerInput carries no field of that name: the OpenXR bindings put
# `/user/hand/right/input/b/click` on SECONDARY_CLICK
# (live_controller_tracker_impl.cpp:292). GHOST_HAND is the right controller.
_RESET_OFFSET_BUTTON = ControllerInputIndex.SECONDARY_CLICK

# The A button, held to put the right thumbstick on the yaw trim instead of the grip
# offset. Modal rather than a second stick because only one controller is wired.
_YAW_TRIM_BUTTON = ControllerInputIndex.PRIMARY_CLICK

# The three external graph leaves feeding EngageAlignmentGate. TeleopSession validates
# every external leaf name is present in external_inputs on EVERY step, independently
# of OptionalType, so all three are sent unconditionally -- absent, not missing, on a
# frame with nothing to say.
#
# The reference is the arm's own gripper pose, which carries the hand's yaw put there by
# Follower.drive, so the two cancel and what the gate measures is the wrist's pitch and
# roll. It is built in before_step, so it lags the controller by one frame; at 72 Hz
# that is 1.25 deg of residual under a 90 deg/s wrist turn, against a 20 deg band.
ENGAGE_REFERENCE_LEAF = "engage_reference"
# The clutch's own engagement, fed back because the graph is acyclic. The PHASE, not
# `clutch.is_engaged`: the phase holds ENGAGED through a brief dropout, which is what
# keeps the recovery latch from being denied for a wrist that has not moved.
CLUTCH_ENGAGED_LEAF = "clutch_engaged"
# The app's extra conjunct. The leader renders the LIMITER's output, so a gate that
# opens while it is still clamping reveals a tool tens of degrees and hundreds of
# milliseconds behind the hand.
LIMITER_PASSING_LEAF = "limiter_passing"

# ── Where the ghost sits on the hand ───────────────────────────────────
# Euler degrees, intrinsic XYZ, i.e. MuJoCo's `euler=`. Solve this rotation from Q_HOME;
# do not port a grip-measured value, which demands a wrist pitch nobody chose. It fixes
# the posture the gate asks for, and this value makes that posture level and unrolled.
# Re-solve when Q_HOME moves: it is the gripper's xquat at Q_HOME and base yaw 0, carried
# into XR by _xr_from_mj_quat, as intrinsic-XYZ Euler.
_EULER_HAND_FROM_GHOST_DEG = (270, 0, 90)
# Measured on a headset: a claim about a hand holding a CONTROLLER, so do not re-derive
# it from the mesh. Relative to HAND_POSE; `_log_hand_frames` prints the replacement
# when that changes.
_POS_HAND_FROM_GHOST = np.array((0, 0, 0))

# ── The trigger hinge ──────────────────────────────────────────────────────
# The follower's `gripper` revolute joint, from SO-ARM100's
# so101_new_calib.urdf: origin xyz="0.0202 0.0188 -0.0234" rpy="1.5708 0 0",
# axis "0 0 1" -- the leader's trigger sits in the moving-jaw slot and shares
# the hinge. The axis below is that "0 0 1" carried through the joint frame's
# 90-degree roll. Do not re-derive either from the meshes: both look right at
# the joint's zero and are wrong by the far end of its travel.
_TRIGGER_HINGE_POS = np.array((0.0202, 0.0188, -0.0234))  # metres, ghost frame
_TRIGGER_HINGE_AXIS = np.array((0.0, -1.0, 0.0))  # unit, ghost frame

# The travel is the URDF joint's own: `upper="1.74533"` is 100.0 degrees, and
# squeezed is its authored zero. Do not extend to the joint's lower limit
# (-10 deg): that end swings the lever 0.4 mm into the servo.
_TRIGGER_RELEASED_RAD = math.radians(100.0)  # closedness 0, jaw wide open
_TRIGGER_SQUEEZED_RAD = 0.0  # closedness 1, tucked to the authored pose


def _quat_from_euler_deg(angles_deg) -> np.ndarray:
    """Intrinsic X-then-Y-then-Z degrees -> a wxyz quaternion, MuJoCo's `euler=`.

    Right-multiplication is what makes it intrinsic. Spelled out rather than calling
    mju_euler2Quat so the sequence is visible where it is used.
    """
    quat = np.array((1.0, 0.0, 0.0, 0.0))
    for axis, angle in zip(np.eye(3), angles_deg):
        step = from_axis_angle(axis, math.radians(angle))
        composed = multiply(quat, step)
        quat = composed
    return quat


# ── Derived below; nothing from here on is authored ────────────────────────
_QUAT_HAND_FROM_GHOST = _quat_from_euler_deg(_EULER_HAND_FROM_GHOST_DEG)


# ── What the harness lets through ──────────────────────────────────────────
# Chosen for this demo, not measured against a follower: ordinary reaching passes
# through and a deliberate flick trips the clamp and then the reject band. An
# SO-101's own envelope is lower -- RateLimiterConfig defaults to 0.25 m/s.
_HARNESS = RateLimiterConfig(
    max_linear_velocity=0.5,  # m/s
    max_angular_velocity=2.5,  # rad/s, ~143 deg/s
    reject_linear_velocity=2.0,  # m/s
    reject_angular_velocity=10.0,  # rad/s
)


_REFERENCE_TYPE = OptionalType(TransformMatrix())
_ENGAGED_TYPE = OptionalType(BoolFlag(EngageAlignmentGate.ENGAGED_INPUT))
_LIMITER_TYPE = OptionalType(BoolFlag(EngageAlignmentGate.APP_PERMITTED_INPUT))


def _flag(tensor_type: OptionalType, value: bool) -> TensorGroup:
    """One frame of a boolean leaf's payload. BoolType wants a real Python bool."""
    group = TensorGroup(tensor_type.inner_type)
    group[EngageAlignmentGate.FLAG_INDEX] = bool(value)
    return group


def _reference(transform: np.ndarray | None) -> OptionalTensorGroup:
    """One frame of the reference leaf; absent before the arm has been placed."""
    group = OptionalTensorGroup(_REFERENCE_TYPE)
    if transform is None:
        group.set_none()
        return group
    group[0] = np.asarray(transform, dtype=np.float32)
    return group


def _build_pipeline(  # noqa: N803
    home_base_T_ee: np.ndarray,
) -> tuple[OutputCombiner, SO101ClutchRetargeter, EngageAlignmentGate]:
    """Controllers, the SO-101 jaw and clutch retargeters, the engage gate and the harness.

    ControllerPoseSource is a parallel branch rather than a link in the clutch's chain: its
    Optional output is the app's only tracking-validity oracle. The jaw is ungoverned.
    Returns the clutch and the gate too, because the app reads `is_engaged` off the one
    and `verdict` off the other.
    """
    controllers = ControllersSource(name="controllers")
    jaw = SO101GripperRetargeter(name="ghost_jaw", input_device=GHOST_HAND).connect(
        {GHOST_HAND: controllers.output(GHOST_HAND)}
    )
    hand = ControllerPoseSource(
        name="hand_pose", pose=HAND_POSE, input_device=GHOST_HAND
    ).connect({GHOST_HAND: controllers.output(GHOST_HAND)})

    gate = EngageAlignmentGate(
        name="engage_gate",
        input_device=GHOST_HAND,
        pose=HAND_POSE,
        app_conjunct=("limiter", "still catching up"),
    )
    permitted = gate.connect(
        {
            GHOST_HAND: controllers.output(GHOST_HAND),
            EngageAlignmentGate.REFERENCE_INPUT: ValueInput(
                ENGAGE_REFERENCE_LEAF, _REFERENCE_TYPE
            ).output(ValueInput.VALUE),
            EngageAlignmentGate.ENGAGED_INPUT: ValueInput(
                CLUTCH_ENGAGED_LEAF, _ENGAGED_TYPE
            ).output(ValueInput.VALUE),
            EngageAlignmentGate.APP_PERMITTED_INPUT: ValueInput(
                LIMITER_PASSING_LEAF, _LIMITER_TYPE
            ).output(ValueInput.VALUE),
        }
    )
    clutch = SO101ClutchRetargeter(
        name="ee_pose",
        home_base_T_ee=home_base_T_ee,
        input_device=GHOST_HAND,
        # The same frame the rest of the app drives from. Its orientation delta is
        # invariant to the choice, so this is here for the translation pivot alone.
        controller_pose=HAND_POSE.value,
    )
    # MEASURED_BASE_T_EE_INPUT is left unwired on purpose: it is position-only
    # (its own docstring carries the measurement), so it cannot put the leader on
    # the follower's orientation.
    commanded = clutch.connect(
        {
            GHOST_HAND: controllers.output(GHOST_HAND),
            SO101ClutchRetargeter.ENGAGE_PERMITTED_INPUT: permitted.output(
                EngageAlignmentGate.PERMITTED_OUTPUT
            ),
        }
    )
    governed = EePoseRateLimiter(name="ghost_harness", config=_HARNESS).connect(
        {EE_POSE_KEY: commanded.output(EE_POSE_KEY)}
    )
    return (
        OutputCombiner(
            {
                ControllersSource.LEFT: controllers.output(ControllersSource.LEFT),
                ControllersSource.RIGHT: controllers.output(ControllersSource.RIGHT),
                GRIPPER_COMMAND_KEY: jaw.output(GRIPPER_COMMAND_KEY),
                HAND_POSE_KEY: hand.output(EE_POSE_KEY),
                COMMANDED_POSE_KEY: commanded.output(EE_POSE_KEY),
                EE_POSE_KEY: governed.output(EE_POSE_KEY),
            }
        ),
        clutch,
        gate,
    )


def _log_startup(resolution, backend: str, gl_device: int) -> None:
    """One block naming every assumption that is invisible at runtime."""
    try:
        version = importlib.metadata.version("isaacteleop")
    except importlib.metadata.PackageNotFoundError:
        version = "<not installed as a distribution>"
    trans = frames.TRANS_MJ_FROM_XR

    LOG.info("scene:      %s", DEFAULT_SCENE)
    # Several examples ship their own .venv, and picking up the wrong
    # isaacteleop is invisible without this line.
    LOG.info(
        "isaacteleop: %s (version %s)", Path(viz.__file__).resolve().parent, version
    )
    # The version the twin is BUILT with, not one the environment supplies: a scene
    # authored against a newer MuJoCo fails to compile with an upstream parser error
    # that names neither, so this line is where the reader learns which one rejected it.
    LOG.info("scene backend: MuJoCo %s (private to the twin)", backend)
    LOG.info(
        "views:      %d (stereo)   view resolution: %sx%s",
        VIEW_COUNT,
        resolution.width,
        resolution.height,
    )
    LOG.info(
        "renderer:   MuJoCo's own (mjr_render), headless EGL on device %d, "
        "offsamples=0; blitted, y-flipped, depth-inverted, read back through a PBO "
        "CUDA imports",
        gl_device,
    )
    LOG.info(
        "clip:       near=%.4f far=%.2f (one pair -> XrTwinSession, projection, submitted depth)",
        NEAR_Z,
        FAR_Z,
    )
    LOG.info(
        "frames:     mj_from_xr translation = (%.3f, %.3f, %.3f) m -- x is operator standoff, "
        "z is a FLOOR datum this session's reference space does not establish (viz.robot.frames)",
        trans[0],
        trans[1],
        trans[2],
    )
    LOG.info("clock:      %s", _CLOCK_SOURCE)
    LOG.info(
        "depth:      D32F requested. Whether the runtime ACCEPTED it is not queryable, so "
        "the absence of errors is not confirmation."
    )


def _pose(result, key: str) -> np.ndarray | None:
    """One of the pipeline's three 7-D pose channels, or None when it carries nothing.

    Carrying nothing has two spellings and `is_none` is only one: for the two REQUIRED
    channels it is hardcoded False, and the limiter keeps a path that returns without
    writing (rate_limiter.py:424-427). Reading an unset tensor raises, and there is no
    "has it been set" predicate, so that raise is the other spelling.
    """
    pose = result[key]
    if pose.is_none:
        return None
    try:
        tensor = pose[0]
    except ValueError:
        return None
    return np.asarray(np.from_dlpack(tensor), dtype=float)


def _xr_from_mj_pos(p_mj: np.ndarray) -> np.ndarray:
    """MuJoCo world point -> XR reference-space point.

    The inverse of `frames.mj_from_xr_pos`, derived from the same two exported
    constants so there is still only one definition of the frame.
    """
    inverse = conjugate(np.array(frames.QUAT_MJ_FROM_XR, dtype=float))
    out = rotate(
        np.asarray(p_mj, dtype=float) - np.array(frames.TRANS_MJ_FROM_XR), inverse
    )
    return out


def _xr_from_mj_quat(q_wxyz: np.ndarray) -> np.ndarray:
    """MuJoCo world orientation (wxyz) -> XR orientation as xyzw."""
    inverse = conjugate(np.array(frames.QUAT_MJ_FROM_XR, dtype=float))
    q_xr = multiply(inverse, np.asarray(q_wxyz, dtype=float))
    return np.array([q_xr[1], q_xr[2], q_xr[3], q_xr[0]])


def ghost_body_from_pose(pose: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A 7-D XR hand pose -> where the leader ghost BODY goes in MuJoCo world.

    The grip calibration lives on this side of the boundary, so follower.py never owns
    it. _QUAT_HAND_FROM_GHOST right-multiplies because it is fixed in the gripper's
    frame; left-multiplying swings the ghost around the room as the operator turns.
    """
    p_xr = [float(pose[0]), float(pose[1]), float(pose[2])]
    q_xyzw = [float(pose[3]), float(pose[4]), float(pose[5]), float(pose[6])]

    q_grip = np.array(frames.mj_from_xr_quat(q_xyzw), dtype=float)
    p_grip = np.array(frames.mj_from_xr_pos(p_xr), dtype=float)

    q_body = multiply(q_grip, _QUAT_HAND_FROM_GHOST)
    p_offset = rotate(_POS_HAND_FROM_GHOST, q_grip)
    return p_grip + p_offset, q_body


def _grip_quat_mj(q_body: np.ndarray) -> np.ndarray:
    """The MuJoCo grip orientation (wxyz) whose ghost body lands at ``q_body``."""
    inverse = conjugate(_QUAT_HAND_FROM_GHOST)
    q_grip = multiply(np.asarray(q_body, dtype=float), inverse)
    return q_grip


def grip_quat_from_ghost_body(q_body: np.ndarray) -> np.ndarray:
    """The XR hand orientation (xyzw) that would put the ghost body at ``q_body``.

    The engage gate's second operand: it is what the clutch will latch, so the gate
    compares the hand against this rather than the tool's own orientation. Both
    operands are xyzw in XR, which is what makes a geodesic angle meaningful.
    """
    return _xr_from_mj_quat(_grip_quat_mj(q_body))


def pose_from_ghost_body(p_body: np.ndarray, q_body: np.ndarray) -> np.ndarray:
    """The exact inverse of :func:`ghost_body_from_pose`, as a 4x4 in the XR frame.

    4x4 because its one consumer is ``SO101ClutchRetargeter.set_home_base_T_ee``, and
    XR because that is the frame the clutch's controller stream is already in -- the
    app does no rebase, so "base" is the XR anchor.
    """
    q_grip = _grip_quat_mj(q_body)
    p_offset = rotate(_POS_HAND_FROM_GHOST, q_grip)

    transform = np.eye(4)
    transform[:3, 3] = _xr_from_mj_pos(np.asarray(p_body, dtype=float) - p_offset)
    q_xyzw = _xr_from_mj_quat(q_grip)
    transform[:3, :3] = to_matrix(
        np.array([q_xyzw[3], q_xyzw[0], q_xyzw[1], q_xyzw[2]])
    )
    return transform


def ghost_bodies(pose: np.ndarray, closedness: float) -> dict:
    """Where the leader gripper's two mocap bodies go, by name.

    `pose` is the harness output, not the controller. Both arguments must be held
    frozen by the caller on an untracked frame -- (0, 0, 0) is the scene origin, and a
    jaw articulating on a frozen body reads as an actuated gripper. Pure: the caller
    publishes the result, and the twin owns the forward kinematics that follow.
    """
    p_body, q_body = ghost_body_from_pose(pose)

    # Rotated ABOUT the hinge, not placed at it: the jaw's XML rest pose equals the
    # ghost's, so the pivot lives in exactly one place.
    angle = _TRIGGER_RELEASED_RAD + closedness * (
        _TRIGGER_SQUEEZED_RAD - _TRIGGER_RELEASED_RAD
    )
    q_hinge = from_axis_angle(_TRIGGER_HINGE_AXIS, angle)
    q_jaw = multiply(q_body, q_hinge)

    # Rotating the ghost frame about the hinge maps 0 to (pivot - R_hinge.pivot).
    swung = rotate(_TRIGGER_HINGE_POS, q_hinge)
    offset = rotate(_TRIGGER_HINGE_POS - swung, q_body)

    return {
        GHOST_BODY: (p_body, q_body),
        GHOST_JAW_BODY: (p_body + offset, q_jaw),
    }


# ── The wrist posture the gate will demand ─────────────────────────────────
# _QUAT_HAND_FROM_GHOST cancels EXACTLY through the engage handoff, so no geometric
# test can discriminate it; its one surviving effect is the wrist posture the operator
# must adopt, which is what this reports. Only the THUMB direction carries it -- the
# tool direction reads 15.2 deg for every calibration swept, so it is a guard on
# Q_HOME. Both are in the OPERATOR'S frame. See README.md.
_OPERATOR_FORWARD = np.array((0.0, 0.0, -1.0))
# Handle centroid to wrist-roll centroid in the ghost body frame, measured on the
# fetched meshes: (-56.9, -0.5, -63.2) mm -> (-4.3, -1.4, -13.2) mm. Rotated below by
# the FOLLOWER `gripper` quaternion, because the handoff puts the ghost body on its
# orientation exactly even though the position comes from the hand.
_GHOST_POINTING_AXIS = np.array((0.7228, -0.0124, 0.6910))
# The -Z of whatever HAND_POSE names, reported so the demanded posture is legible. What
# it MEANS depends on that constant: on GRIP it is the thumb axis, up through the fist;
# on AIM it is the pointing ray. The angle is only "comfortable to hold" on the reading
# that matches, so read the log's wording and not just the number.
_HAND_REPORT_AXIS = np.array((0.0, 0.0, -1.0))
# Warned on, never asserted: test-bounding the posture angle would pin it and
# make _EULER_HAND_FROM_GHOST_DEG untunable on a headset, which is the one place it
# can be tuned.
_POSTURE_LIMIT_DEG = 45.0

# Which axis of HAND_POSE the yaw drive reads: aim's -Z, the pointing ray. Every axis
# tracks a world-vertical turn 1:1 and is blind to rotation about itself, so the choice
# only decides how much wrist roll and pitch leak into the arm's yaw. README.md
# tabulates the leak per candidate, measured on grip; aim's is unmeasured here because
# the grip-to-aim transform is per-device. Re-measure on a headset before trusting it.
_HAND_FORWARD_AXIS = np.array((0.0, 0.0, -1.0))

# Whatever azimuth is left between where the operator means to point and what the app
# reads. On AIM this SHOULD be zero -- that is the entire reason for reading aim -- so a
# session that has to dial in a large value is evidence the switch did not do its job,
# not a knob to lean on. Kept because it is the only thing that can absorb a runtime
# whose aim convention differs from the operator's expectation. Tuned on a headset: hold
# A and push the right thumbstick, then paste back what the app prints. Degrees, positive
# turning the arm the way a positive XR yaw does, applied as a constant on top of the
# reading so it cannot introduce leakage of its own.
_YAW_TRIM_DEG = 0.0
_YAW_TRIM_RATE_DEG_S = 20.0


def hand_facing_xr(q_hand_xyzw: np.ndarray) -> np.ndarray:
    """The XR yaw (wxyz) the operator's hand is facing, for the follower's base."""
    return yaw_of_axis(q_hand_xyzw, _HAND_FORWARD_AXIS)


def _log_hand_frames(result) -> bool:
    """Measure the device's grip-to-aim transform and print the calibration it implies.

    The grip-to-aim transform is per-device, so no constant can carry
    :data:`_POS_HAND_FROM_GHOST` across a :data:`HAND_POSE` change -- but the runtime
    publishes both poses on one controller, so one frame with both valid yields the
    replacement. Position only: porting the rotation would hand back the wrist pitch that
    solving it from Q_HOME removes. Returns whether it got a reading. Never raises.
    """
    try:
        controller = result[GHOST_HAND]
        if controller.is_none or not (
            bool(controller[ControllerInputIndex.GRIP_IS_VALID])
            and bool(controller[ControllerInputIndex.AIM_IS_VALID])
        ):
            return False
        grip = np.asarray(
            controller[ControllerInputIndex.GRIP_ORIENTATION], dtype=float
        )
        aim = np.asarray(controller[ControllerInputIndex.AIM_ORIENTATION], dtype=float)
        grip_pos = np.asarray(
            controller[ControllerInputIndex.GRIP_POSITION], dtype=float
        )
        aim_pos = np.asarray(controller[ControllerInputIndex.AIM_POSITION], dtype=float)
        if min(np.linalg.norm(aim), np.linalg.norm(grip)) < MIN_QUAT_NORM:
            return False
    except (ValueError, IndexError, TypeError):
        return False

    # aim^-1 . grip, wxyz: what carries a direction from the GRIP frame into AIM's.
    inverse = conjugate(aim[[3, 0, 1, 2]])
    aim_from_grip = multiply(inverse, grip[[3, 0, 1, 2]])
    # The ghost offset is applied in the hand's frame, so carrying it across costs both
    # terms: the origins' separation pulled back into the new frame, and the old offset
    # turned by the same rotation the orientation above is. Dropping the second leaves
    # the ghost centimetres out while its orientation looks perfect.
    separation = rotate(grip_pos - aim_pos, inverse)
    turned = rotate(np.asarray(_POS_HAND_FROM_GHOST, dtype=float), aim_from_grip)
    offset = separation + turned

    LOG.info(
        "hand frames: this device's aim pose sits %.0f deg and %.0f mm off its grip "
        "pose. HAND_POSE is %s, so for the ghost to sit where it did on GRIP, its "
        "position wants:",
        math.degrees(2.0 * math.acos(min(1.0, abs(float(aim_from_grip[0]))))),
        1000.0 * float(np.linalg.norm(grip_pos - aim_pos)),
        HAND_POSE.value.upper(),
    )
    LOG.info(
        "hand frames:   _POS_HAND_FROM_GHOST = np.array((%.3f, %.3f, %.3f))", *offset
    )
    return True


def base_yaw_bias(arm) -> np.ndarray:
    """How far the base yaw must LEAD the hand for the JAW to face it (wxyz).

    Measured off the arm at startup rather than authored: how far the jaw sits off its
    base yaw follows from Q_HOME and upstream's chain, J5 above all. Both operands are
    yaws about +Y, so the order is free.
    """
    inverse = conjugate(arm.jaw_yaw_xr)
    bias = multiply(arm.base_yaw_xr, inverse)
    return bias


def _log_grip_posture(arm) -> tuple[float, float]:
    """Invert the chain at Q_HOME and report the posture the gate will ask for.

    Both angles are un-yawed into the operator's own frame, so they read the same
    whichever way they face -- which is also what lets this run before the anchor. Warns
    rather than raises: this app is the only place the calibration can be judged.
    """
    p_body, q_body = arm.gripper_pose_mj()
    ghost_axis = rotate(_GHOST_POINTING_AXIS, q_body)
    # The OPERATOR's frame is the HAND's yaw, which the base leads by base_yaw_bias.
    # Un-yawing by the base instead reports the demand a whole bias out, which is
    # invisible while that bias is small and wrong by 93 degrees once it is not.
    inverse_bias = conjugate(base_yaw_bias(arm))
    hand_yaw = multiply(arm.base_yaw_xr, inverse_bias)
    unyaw = conjugate(hand_yaw)

    def in_operator_frame(direction_xr):
        out = rotate(np.asarray(direction_xr, dtype=float), unyaw)
        return out

    tool = in_operator_frame(
        _xr_from_mj_pos(p_body + ghost_axis) - _xr_from_mj_pos(p_body)
    )
    hand_axis = in_operator_frame(
        pose_from_ghost_body(p_body, q_body)[:3, :3] @ _HAND_REPORT_AXIS
    )

    def ahead(direction):
        return math.degrees(
            math.acos(min(1.0, max(-1.0, float(direction @ _OPERATOR_FORWARD))))
        )

    LOG.info(
        "grip calib: at Q_HOME the tool points (%+.2f, %+.2f, %+.2f), %.0f deg off the "
        "operator's forward, and the gate will demand a hand whose %s axis is "
        "(%+.2f, %+.2f, %+.2f), %.0f deg off. XR axes, in the operator's frame. Only the "
        "SECOND depends on _EULER_HAND_FROM_GHOST_DEG.",
        *tool,
        ahead(tool),
        "pointing" if HAND_POSE is HandPose.AIM else "thumb",
        *hand_axis,
        ahead(hand_axis),
    )
    # The hand axis only: the tool angle does not depend on the calibration at all, so a
    # warning on it would report a Q_HOME or mesh change under a misleading name.
    if ahead(hand_axis) > _POSTURE_LIMIT_DEG:
        LOG.warning(
            "grip calib: the gate will demand a hand held %.0f deg off neutral, past the "
            "%.0f deg that reads as a comfortable hold. Check _EULER_HAND_FROM_GHOST_DEG "
            "-- it is the only constant this angle depends on.",
            ahead(hand_axis),
            _POSTURE_LIMIT_DEG,
        )
    return ahead(tool), ahead(hand_axis)


def run() -> int:
    twin = SceneTwin(DEFAULT_SCENE)
    # Before the Renderer, which uploads geometry once: the follower repoints geom
    # materials and poses its joints here. Not placed yet -- that waits for the first
    # head pose, in _Preview.before_step.
    arm = follower.Follower(twin)
    monitor = InterventionMonitor(twin)

    # The clutch's home is pushed every non-ENGAGED frame, so this constructor value
    # only has to be well-formed -- nothing can latch before the anchor exists.
    pipeline, clutch, gate = _build_pipeline(
        pose_from_ghost_body(*arm.gripper_pose_mj())
    )
    preview = _Preview(twin, monitor, arm, clutch, gate)

    teleop_config = TeleopSessionConfig(
        app_name="RobotViz",
        pipeline=pipeline,
        # Never pass trackers=: TeleopSession discovers them from the graph, and
        # passing them again duplicates the set. It also aggregates their OpenXR
        # extensions and hands that list to the twin's xrCreateInstance, which is why
        # nothing here calls get_required_oxr_extensions_from_pipeline.
        joint_publisher=twin,
        twin_render=TwinRenderConfig(near_z=NEAR_Z, far_z=FAR_Z),
    )
    with TeleopSession(teleop_config) as teleop_session:
        _log_startup(
            teleop_session.twin_resolution, twin.backend_version, twin.gl_device_index
        )
        LOG.info(
            "leader ghost: %s / %s driven as mocap bodies; trigger driven by "
            "SO101GripperRetargeter, %.0f deg released to %.0f deg squeezed",
            GHOST_BODY,
            GHOST_JAW_BODY,
            math.degrees(_TRIGGER_RELEASED_RAD),
            math.degrees(_TRIGGER_SQUEEZED_RAD),
        )
        arm.log_placement()
        # Before the anchor, and correct there: both angles are reported in the
        # operator's own frame, which the anchor's yaw is exactly what defines.
        _log_grip_posture(arm)
        LOG.info(
            "harness:    the ghost renders the EePoseRateLimiter output, clamped at "
            "%.2f m/s / %.0f deg/s and rejecting above %.2f m/s / %.0f deg/s. Amber "
            "while clamping, red while rejecting, authored blue passing through.",
            _HARNESS.max_linear_velocity,
            math.degrees(_HARNESS.max_angular_velocity),
            _HARNESS.reject_linear_velocity,
            math.degrees(_HARNESS.reject_angular_velocity),
        )
        try:
            _loop(teleop_session, preview)
        finally:
            LOG.info(monitor.summary())
    if teleop_session.twin_teardown_clean is False:
        # The render thread is still inside the runtime, so CloudXRLauncher must not
        # stop a runtime it owns on the way out -- see TeleopSession.twin_teardown_clean.
        LOG.error(
            "the twin's render thread did not exit; leaving the OpenXR session and "
            "the runtime alive. This process will not exit until it completes."
        )
        return 1
    return 0


# ── The per-frame protocol ─────────────────────────────────────────────────
# It spans four files, so it is stated once, here. Each frame, in order:
#
#   1. before_step()  -- anchor the arm to the head if it is not anchored yet,
#                        push the hand's position at the follower's rotation as
#                        the clutch home (every non-ENGAGED frame), and emit the
#                        gate's three leaves.
#   2. step()         -- the retargeting graph runs: jaw, grip source, gate,
#                        clutch, limiter. The gate judges THIS frame's controller
#                        and the clutch reads its verdict on the same frame.
#   3. after_step()   -- advance the phase, drive the arm, write the ghost's
#                        mocap rows, mj_forward, publish the gate's verdict.
#   4. render         -- mjv_updateScene reads geom_xpos, then submit.
#
# The three leaves are one frame stale, deliberately: step N's leaves carry what
# after_step produced on frame N-1, because the gate needs a limiter band and an arm
# pose step N has not computed yet. Squeezing inside that 14 ms costs nothing -- a
# denied latch stays OWED and fires on the first permitted frame.
class _Preview:
    """The follower/leader handoff: one call before ``step()``, one after.

    Everything in ``_loop`` that is not rendering. Split out so the whole engage
    sequence can be driven headlessly at frame rate, which is the only way to exercise
    the gate's pass-through conjunct -- a quasi-static drive passes it by luck.
    """

    def __init__(self, twin, monitor, arm, clutch, gate) -> None:
        """Bind to one twin, one pair of tools, one clutch and the gate node.

        Measures the arm's yaw bias here, while the base still stands on the yaw
        ``Follower.__init__`` left it on -- ``anchor`` has not run, so the reading is the
        arm's own and not a head's.
        """
        self._twin = twin
        self._monitor = monitor
        self._arm = arm
        self._clutch = clutch
        self._gate = gate
        # Named rather than discovered, so a renamed geom is an error.
        twin.declare_group(GHOST_GROUP, geoms=GHOST_GEOMS)
        self.phases = follower.PhaseMachine()
        # The gate's own pre-first-step verdict, which reports that nothing has been
        # judged rather than reading as engageable.
        self.verdict = gate.verdict
        # The gate's extra conjunct, latched by after_step because before_step runs a
        # frame ahead of the limiter band it is read off.
        self._limiter_passing = False
        # Neither tool is drawn until the arm is anchored, so start both hidden rather
        # than relying on the first after_step to arrive.
        twin.publish(groups={GHOST_GROUP: False})
        # SO101GripperRetargeter's own released end, held until the first frame with a
        # usable hand pose refreshes it.
        self._closedness = 0.0
        # B is edge-triggered, so a held button resets the offset once.
        self._reset_held = False
        # The ghost body of the last usable hand pose, latched by after_step because
        # before_step runs a frame ahead of it. None until one arrives, and no latch can
        # be permitted before then: the gate reports `controller not tracked`.
        self._hand_body_mj: np.ndarray | None = None
        self._yaw_bias = base_yaw_bias(arm)
        self._yaw_trim_deg = _YAW_TRIM_DEG
        self._trimming = False
        # One reading is all it takes, and it needs a tracked controller, so it cannot
        # happen at construction.
        self._frames_logged = False
        LOG.info(
            "follower:   the base leads the hand by %+.2f deg of yaw, measured off "
            "Q_HOME so the JAW faces where the controller does.",
            math.degrees(2.0 * math.atan2(self._yaw_bias[2], self._yaw_bias[0])),
        )

    def before_step(self, head: np.ndarray | None) -> tuple[dict, ExecutionEvents]:
        """Anchor the arm if it is not anchored, then build this frame's step() kwargs.

        Two rules on the home push. Key it off the app's phase, never
        ``clutch.is_engaged``, which drops on four paths of which one is a real disengage;
        and take the position from the hand and the rotation from the gripper, so the
        leader appears in the operator's hand at the rotation they aimed. The gripper's
        own position would carry the preview's offset into the clutch's delta.
        """
        if head is not None and not self._arm.anchored:
            self._arm.anchor(head)
        if (
            self.phases.phase is not follower.ClutchPhase.ENGAGED
            and self._hand_body_mj is not None
        ):
            self._clutch.set_home_base_T_ee(
                pose_from_ghost_body(self._hand_body_mj, self._arm.gripper_pose_mj()[1])
            )
        # The reset pulse re-seeds the limiter's baseline onto the first frame after a
        # disengage, where the commanded pose jumps from the leader back to the
        # follower. Without it the limiter rejects for ~30 frames (0.92 s).
        # execution_state is spelled out because ExecutionEvents defaults to UNKNOWN,
        # which would make the clutch silently never engage.
        reset = self.phases.reset_requested
        self.phases.reset_requested = False
        # Absent until the arm is placed, which the gate reports as `no reference pose`
        # rather than reading as aligned.
        reference = (
            pose_from_ghost_body(*self._arm.gripper_pose_mj())
            if self._arm.anchored
            else None
        )
        return (
            {
                ENGAGE_REFERENCE_LEAF: {ValueInput.VALUE: _reference(reference)},
                CLUTCH_ENGAGED_LEAF: {
                    ValueInput.VALUE: _flag(
                        _ENGAGED_TYPE, self.phases.permits_engagement
                    )
                },
                LIMITER_PASSING_LEAF: {
                    ValueInput.VALUE: _flag(_LIMITER_TYPE, self._limiter_passing)
                },
            },
            ExecutionEvents(reset=reset, execution_state=ExecutionState.RUNNING),
        )

    def after_step(self, result, dt: float) -> follower.ClutchPhase:
        """Advance the phase, drive both tools, and re-evaluate the gate."""
        if not self._arm.anchored:
            # Nowhere to put the arm yet, so before_step sent no reference and the gate
            # blocked on it. Draw neither tool. Returns before the phase machine, so a
            # frame with no placement is a frame that did not happen.
            self._show(follower_visible=False, ghost_visible=False)
            self._blocked(self._gate.verdict)
            return self.phases.phase

        # HAND_POSE_KEY is the only channel that can report tracking loss.
        hand = _pose(result, HAND_POSE_KEY)
        commanded = _pose(result, COMMANDED_POSE_KEY)
        governed = _pose(result, EE_POSE_KEY)

        # ControllerPoseSource drops on the pose's IS_VALID; the clutch ALSO disarms on a
        # non-finite pose and on a finite but degenerate quaternion. Both folded in, so
        # `hand` covers the clutch's whole disarm set -- otherwise a bad frame leaves
        # hand_present True while is_engaged has just gone False, and the phase machine
        # reads that as a real disengage.
        #
        # `is_unit` is WIDER than the clutch's own norm floor, deliberately: a norm-0.5
        # quaternion clears that floor and then raises out of yaw_of_axis, on the frame
        # loop, ending the session. Erring wide costs at worst a phase dropout the arm
        # freezes through.
        if hand is not None and (
            not np.all(np.isfinite(hand[:3])) or not is_unit(hand[3:7])
        ):
            hand = None

        # Latched, and refreshed only on a usable frame. SO101GripperRetargeter tests
        # `inp.is_none` alone, so it keeps articulating the trigger while GRIP_IS_VALID
        # is false, and a jaw swinging on a frozen body reads as "the gripper actuated".
        if hand is not None:
            self._closedness = float(result[GRIPPER_COMMAND_KEY][0])
            # Latched for the same reason and one of its own: `before_step` pushes the
            # clutch's home a frame before this one exists. Taken from the hand rather
            # than read back off the arm, so the grip offset -- tuned or not -- cannot
            # leak into an engagement the clutch composes as a delta.
            self._hand_body_mj = ghost_body_from_pose(hand)[0]

        if not self._frames_logged:
            self._frames_logged = _log_hand_frames(result)

        # Before the phase advance, so a press takes effect on this frame rather
        # than the next.
        self._reset_offset(result)

        phase = self.phases.advance(
            is_engaged=self._clutch.is_engaged, hand_present=hand is not None, dt=dt
        )

        # Nothing moves the arm while ENGAGED -- it is hidden and frozen where it stood
        # on the engage frame. The disengage edge lands DISENGAGED, so the drag resumes
        # on that very frame with no ramp in between.
        if phase is follower.ClutchPhase.DISENGAGED and hand is not None:
            # The hand, not the governed pose: the limiter governs only what the leader
            # renders. Raw XR, not the ghost body -- follower.py is free of the grip
            # calibration and must stay that way.
            stick_x, stick_y = self._stick(result)
            if self._trim_yaw(result, stick_x, dt):
                # A owns the stick while held, so a trim cannot also walk the offset.
                stick_x = stick_y = 0.0
            facing, base_yaw = self._yaws(hand[3:7])
            self._arm.drive(hand[:3], facing, base_yaw, stick_x, stick_y, dt)

        engaged = phase is follower.ClutchPhase.ENGAGED
        self._show(follower_visible=not engaged, ghost_visible=engaged)

        self._limiter_passing = False
        if commanded is not None and governed is not None:
            # The body needs no tracking-loss gate: the clutch emits its held pose on
            # every disarm path, so the pipeline freezes it. The JAW does, hence the
            # latch above.
            self._twin.publish(bodies=ghost_bodies(governed, self._closedness))
            # Classified on every governed frame, painted only while the ghost is the
            # tool on show: the band needs an unbroken baseline to tell a refused frame
            # from a clamped one.
            band = self._monitor.update(commanded, governed, paint=engaged)
            self._limiter_passing = band is HarnessBand.PASS_THROUGH

        self._blocked(self._gate.verdict)
        return phase

    def _yaws(self, q_hand_xyzw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``(where the controller points, what to turn the base onto)``, both wxyz.

        The app's half of the yaw drive, and the whole of it: which axis of a pose is its
        facing is a fact about the calibration, so follower.py is handed the answer. The
        second leads the first by the measured bias and the operator's trim, all yaws
        about +Y, so their order is free. The follower needs both -- the base takes the
        second, the grip offset is carried on the first.
        """
        facing = hand_facing_xr(q_hand_xyzw)
        trim = from_axis_angle(
            np.array([0.0, 1.0, 0.0]), math.radians(self._yaw_trim_deg)
        )
        biased = multiply(facing, self._yaw_bias)
        base_yaw = multiply(biased, trim)
        return facing, base_yaw

    def _trim_yaw(self, result, stick_x: float, dt: float) -> bool:
        """A + the right thumbstick: walk the yaw trim. True while it owns the stick.

        A rate, like the grip offset, so the trim holds where the stick left it. Logs
        once on the release in the constant's own form, with what the AIM pose would
        have said beside it.
        """
        controller = result[GHOST_HAND]
        held = not controller.is_none and bool(controller[_YAW_TRIM_BUTTON])
        if not held:
            if self._trimming:
                self._trimming = False
                LOG.info(
                    "follower:   yaw trim -> _YAW_TRIM_DEG = %.1f", self._yaw_trim_deg
                )
            return False
        step = follower.deflection(stick_x) * _YAW_TRIM_RATE_DEG_S * float(dt)
        self._yaw_trim_deg += step
        # Only a stick that actually moved arms the log, so holding A to keep the trim
        # off the grip offset does not print a line every time it is released.
        self._trimming = self._trimming or step != 0.0
        return True

    def _stick(self, result) -> tuple[float, float]:
        """The right thumbstick's two raw axes, or a stick at rest.

        ``Follower.drive`` owns which way each one points: the horizontal drive has one
        definition and it is not here.
        """
        controller = result[GHOST_HAND]
        if controller.is_none:
            # Absent before the tracker has a controller, and reading the group there
            # raises rather than reporting a stick at rest -- see `_reset_offset`.
            return 0.0, 0.0
        return (
            float(controller[ControllerInputIndex.THUMBSTICK_X]),
            float(controller[ControllerInputIndex.THUMBSTICK_Y]),
        )

    def _reset_offset(self, result) -> None:
        """B, on its rising edge: put the grip offset back to its authored value.

        The operator's escape hatch, so deliberately phase-free. Needs no pose: the
        offset is a constant in the anchor's frame, not a point in the world.
        """
        # The controller group is Optional and absent before the tracker has one;
        # reading it there raises rather than returning a falsy button, which took the
        # whole session down at startup. Absent is "not pressed", so a press spanning a
        # dropout re-arms and the first tracked frame is a fresh rising edge.
        controller = result[GHOST_HAND]
        pressed = not controller.is_none and bool(controller[_RESET_OFFSET_BUTTON])
        rising = pressed and not self._reset_held
        self._reset_held = pressed
        if not rising:
            return
        self._arm.reset_offset()
        LOG.info(
            "follower:   grip offset reset to XR (%.2f, %.2f, %.2f).",
            *self._arm.grip_from_controller_xr,
        )

    def _show(self, *, follower_visible: bool, ghost_visible: bool) -> None:
        """The only place either tool's visibility is set. At most one is drawn."""
        self._arm.set_visible(follower_visible)
        self._twin.publish(groups={GHOST_GROUP: ghost_visible})

    def _blocked(self, verdict: GateVerdict) -> None:
        """Publish the gate's verdict: the arm's colour, and a log on transitions.

        Keyed on `verdict.keys`, never on the text it renders. The verdict is stored
        even on frames nothing is logged, so the first frame after a release is
        compared against the last engaged one and the release is always heard.
        """
        previous_keys = self.verdict.keys
        self.verdict = verdict
        self._arm.set_engageable(verdict.ok)
        if verdict.keys == previous_keys or KEY_ENGAGED in verdict.keys:
            return
        LOG.info(
            "clutch: %s",
            "engageable"
            if verdict.ok
            else "blocked (" + "; ".join(verdict.blocked) + ")",
        )


# The control loop's cadence. Wall-clock paced and independent of the display: the
# render thread runs at whatever the runtime hands it, and the graph has no reason to
# match. 30 Hz is the rate a real SO-101 loop runs at, so the preview behaves like one.
CONTROL_HZ = 30.0
_CONTROL_DT = 1.0 / CONTROL_HZ


def _loop(teleop_session, preview: _Preview) -> None:
    """Step the graph at :data:`CONTROL_HZ` for as long as the twin is being drawn.

    Nothing here renders. The head pose comes off the session, which publishes whatever
    the render thread last saw -- the arm is anchored to where the operator stood, once,
    so a pose one frame old is the same pose.
    """
    deadline = time.perf_counter()
    while teleop_session.twin_rendering:
        external_inputs, events = preview.before_step(teleop_session.twin_head_pose)
        result = teleop_session.step(
            external_inputs=external_inputs, execution_events=events
        )
        preview.after_step(result, _CONTROL_DT)
        deadline += _CONTROL_DT
        time.sleep(max(0.0, deadline - time.perf_counter()))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--verbose", action="store_true", help="Debug-level logging.")
    CloudXRLauncher.add_launcher_arguments(parser)
    args = parser.parse_args(argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[robot_viz] %(message)s",
    )

    # Before launch_context starts the runtime, so an unfetched checkout says so
    # plainly rather than buried in the runtime's startup logging.
    missing = _missing_assets()
    if missing:
        raise SystemExit(
            f"robot_viz: the SO-101 assets are not fetched ({', '.join(missing)}).\n"
            f"  Run {FETCH_SCRIPT} from the repository root, then reinstall:\n"
            "  uv pip install --reinstall-package isaacteleop-examples-robot-viz "
            "./examples/robot_viz"
        )

    with CloudXRLauncher.launch_context(args) as launcher:
        if launcher.owns_runtime:
            LOG.info("CloudXR runtime started (WSS log: %s)", launcher.wss_log_path)
        try:
            return run()
        except KeyboardInterrupt:
            LOG.info("interrupted")
            return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
