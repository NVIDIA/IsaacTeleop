# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A MuJoCo scene drawn into a Televiz XR session.

One OpenXR session shared between VizSession (rendering) and TeleopSession
(input); the scene is drawn by MuJoCo's own renderer and reaches
ProjectionLayer.submit() by CUDA pointer, never through host memory.

    VizSession(kXr)  ──get_oxr_handles()──▶  TeleopSession
         │                                        │
         │ recommended resolution                 │ EePoseRateLimiter output
         ▼                                        ▼                      │
    _mujoco_xr.Renderer  ──__cuda_array_interface__──▶  ProjectionLayer  │
         ▲                                                               │
         └──────────────── mjData.mocap_pos/_quat ◀─────────────────────┘

The renderer needs an OpenGL context current on this thread; viz and the renderer
meet through CUDA alone, on VizSession's GPU. C++ owns
mjvScene/mjvOption/mjvCamera/mjrContext, Python owns mjModel/mjData.

Nothing is integrated -- mj_step is never called -- which makes one invariant
load-bearing: **one mj_forward after every `qpos`, `body_pos` or `mocap_*` write,
before every `xpos` / `xquat` / `geom_xpos` read, including the read inside
mjv_updateScene.** `mocap_*` is an INPUT to forward kinematics; the renderer draws
`geom_xpos`. See README.md for the rest of the design.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import logging
import math
import sys
from pathlib import Path
from typing import NamedTuple

import mujoco
import numpy as np

from isaacteleop import viz
from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.oxr import OpenXRSessionHandles
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import (
    ExecutionEvents,
    ExecutionState,
    OutputCombiner,
    TensorGroup,
    ValueInput,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import BoolType, ControllerInputIndex
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
from isaacteleop.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig,
    get_required_oxr_extensions_from_pipeline,
)

from . import _mujoco_xr, follower
from .harness import ControllerPoseSource, HandPose, HarnessBand, InterventionMonitor

LOG = logging.getLogger("mujoco_xr")

# The app's only clip planes. VizSessionConfig, the projection and the submitted depth
# must all agree, or world-locked geometry swims under head motion, and only a headset
# shows it. There is no near/far literal in cpp/, by construction.
NEAR_Z = 0.05
FAR_Z = 50.0

# Wall-clock ceiling for one advance of the app's own clock. See _clamp_dt.
MAX_DT_S = 0.1

# The only mode: this needs a headset and a CloudXR runtime. A headless fallback
# should arrive with the CI job that runs it (NVIDIA/IsaacTeleop#880).
_DISPLAY_MODE = viz.DisplayMode.kXr

# layer.submit() in _loop is spelled out per eye and cannot read this name, so
# changing it means editing that call too.
_VIEW_COUNT = 2

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
FETCH_SCRIPT = "examples/mujoco_xr/scripts/fetch-so-arm.sh"
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

# The four ghost geoms, hidden as a set whenever the follower is the tool on
# show. Named here rather than discovered, so a renamed geom is an error.
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

# The external graph leaf carrying the engage gate's verdict. TeleopSession validates
# every external leaf name is present in external_inputs on EVERY step, independently
# of OptionalType, so this key is sent unconditionally.
ENGAGE_PERMISSION_LEAF = "engage_permission"

# The clutch's own degenerate-quaternion threshold (clutch_retargeter.py:109),
# restated so `after_step`'s usable-pose test covers its whole disarm set. Reused
# for the head pose, which has no such consumer but is just as unusable at zero.
_MIN_QUAT_NORM = 1e-6

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
        step = np.empty(4)
        mujoco.mju_axisAngle2Quat(step, axis, math.radians(angle))
        composed = np.empty(4)
        mujoco.mju_mulQuat(composed, quat, step)
        quat = composed
    return quat


# ── Derived below; nothing from here on is authored ────────────────────────
_QUAT_HAND_FROM_GHOST = _quat_from_euler_deg(_EULER_HAND_FROM_GHOST_DEG)


def _clamp_dt(dt: float) -> float:
    """NaN-safe clamp into [0, MAX_DT_S].

    Comparisons, not min/max: max(nan, 0) is nan, so the obvious form passes NaN
    through both limits and into whatever accumulates it.
    """
    if dt > 0:
        return MAX_DT_S if dt > MAX_DT_S else dt
    return 0.0


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


_PERMISSION_TYPE = TensorGroupType(
    SO101ClutchRetargeter.ENGAGE_PERMITTED_INPUT, [BoolType("permitted")]
)


def _permission(permitted: bool) -> TensorGroup:
    """One frame of the permission leaf's payload. BoolType wants a real Python bool."""
    group = TensorGroup(_PERMISSION_TYPE)
    group[SO101ClutchRetargeter.PERMITTED_INDEX] = bool(permitted)
    return group


def _build_pipeline(  # noqa: N803
    home_base_T_ee: np.ndarray,
) -> tuple[OutputCombiner, SO101ClutchRetargeter]:
    """Controllers, the SO-101 jaw and clutch retargeters, and the pose harness.

    ControllerPoseSource is a parallel branch rather than a link in the clutch's chain: its
    Optional output is the app's only tracking-validity oracle. The jaw is ungoverned.
    Returns the clutch too, because the app reads `is_engaged` off it.
    """
    controllers = ControllersSource(name="controllers")
    jaw = SO101GripperRetargeter(name="ghost_jaw", input_device=GHOST_HAND).connect(
        {GHOST_HAND: controllers.output(GHOST_HAND)}
    )
    hand = ControllerPoseSource(
        name="hand_pose", pose=HAND_POSE, input_device=GHOST_HAND
    ).connect({GHOST_HAND: controllers.output(GHOST_HAND)})
    permission = ValueInput(ENGAGE_PERMISSION_LEAF, OptionalType(_PERMISSION_TYPE))
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
            SO101ClutchRetargeter.ENGAGE_PERMITTED_INPUT: permission.output(
                ValueInput.VALUE
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
    )


def _head_pose(info) -> np.ndarray | None:
    """FrameInfo.views[0] as a 7-D XR pose (position, xyzw), or None if unusable.

    The left eye rather than a head centre, which the runtime does not report; the
    ~32 mm between them is well inside what HOME_GRIP_FROM_HEAD_XR is authored to.
    """
    if len(info.views) == 0:
        return None
    view = info.views[0]
    px, py, pz = view.pose.position
    qw, qx, qy, qz = view.pose.orientation
    pose = np.array([px, py, pz, qx, qy, qz, qw], dtype=float)
    if (
        not np.all(np.isfinite(pose))
        or float(np.linalg.norm(pose[3:7])) < _MIN_QUAT_NORM
    ):
        return None
    return pose


def _flatten_xr_views(info) -> tuple[list[float], list[float]]:
    """FrameInfo.views -> the flat float arrays the renderer takes.

    Field by field, never sliced: viz.Pose3D.orientation is (w,x,y,z) while a
    controller's GRIP_ORIENTATION is (x,y,z,w).
    """
    poses: list[float] = []
    fovs: list[float] = []
    for view in info.views:
        px, py, pz = view.pose.position
        qw, qx, qy, qz = view.pose.orientation
        poses.extend((px, py, pz, qw, qx, qy, qz))
        fovs.extend(
            (
                view.fov.angle_left,
                view.fov.angle_right,
                view.fov.angle_up,
                view.fov.angle_down,
            )
        )
    return poses, fovs


def _assert_frustum(f: list[float], fov, near: float, far: float) -> None:
    """The frustum handed to mjvGLCamera, checked against the fov it came from.

    `f` is (center, half_width, bottom, top, near, far). The projection's shape
    is MuJoCo's business; which numbers reach it is this app's.
    """
    center, half_width, bottom, top, f_near, f_far = f

    # At zero half_width mjr_render derives the horizontal extent from the
    # viewport aspect, rendering something plausible from a fov carrying nothing.
    assert half_width > 0.0 and top > bottom, (
        f"degenerate frustum {f}: a zeroed Fov reached the camera"
    )
    # float32 tolerances throughout: the frustum crosses as C floats, so an
    # exact comparison against a Python float fails on rounding alone.
    for name, got, want in (
        ("left", center - half_width, near * math.tan(fov.angle_left)),
        ("right", center + half_width, near * math.tan(fov.angle_right)),
        ("bottom", bottom, near * math.tan(fov.angle_down)),
        ("top", top, near * math.tan(fov.angle_up)),
    ):
        assert abs(got - want) <= 1e-6 * max(1.0, abs(want)), (
            f"frustum {name}={got}, expected {want}"
        )

    # viz's XrCompositionLayerDepthInfoKHR pair must be the encoding pair, or
    # the runtime reprojects against the wrong range.
    assert abs(f_near - near) <= 1e-6 * near and abs(f_far - far) <= 1e-6 * far, (
        f"clip planes drifted: camera has ({f_near}, {f_far}), viz was told ({near}, {far})"
    )


def _log_startup(resolution, gl_backend: str) -> None:
    """One block naming every assumption that is invisible at runtime."""
    try:
        version = importlib.metadata.version("isaacteleop")
    except importlib.metadata.PackageNotFoundError:
        version = "<not installed as a distribution>"
    trans = _mujoco_xr.TRANS_MJ_FROM_XR

    LOG.info("scene:      %s", DEFAULT_SCENE)
    # Several examples ship their own .venv, and picking up the wrong
    # isaacteleop is invisible without this line.
    LOG.info(
        "isaacteleop: %s (version %s)", Path(viz.__file__).resolve().parent, version
    )
    LOG.info(
        "mujoco:     %s (extension links %s)",
        mujoco.mj_versionString(),
        _mujoco_xr.mujoco_version(),
    )
    LOG.info(
        "views:      %d (stereo)   view resolution: %sx%s",
        _VIEW_COUNT,
        resolution.width,
        resolution.height,
    )
    LOG.info(
        "renderer:   MuJoCo's own (mjr_render), OpenGL backend %s, offsamples=0; "
        "blitted, y-flipped, depth-inverted, read back through a PBO CUDA imports",
        gl_backend,
    )
    LOG.info(
        "clip:       near=%.4f far=%.2f (one pair -> VizSessionConfig, projection, submitted depth)",
        NEAR_Z,
        FAR_Z,
    )
    LOG.info(
        "frames:     mj_from_xr translation = (%.3f, %.3f, %.3f) m -- x is operator standoff, "
        "z is a FLOOR datum this session's reference space does not establish (cpp/frames.hpp)",
        trans[0],
        trans[1],
        trans[2],
    )
    LOG.info("clock:      %s", _CLOCK_SOURCE)
    LOG.info(
        "depth:      D32F requested. Whether the runtime ACCEPTED it is not queryable, so "
        "the absence of errors is not confirmation."
    )


class _GhostChannels(NamedTuple):
    """The ghost's two mocap rows, resolved once at startup.

    Mocap indices, not body ids: mocap_pos/mocap_quat index by body_mocapid,
    and a body id there writes into another body's row.
    """

    body: int
    jaw: int


def _resolve_ghost(model) -> _GhostChannels:
    """Both ghost mocap rows. The shipped scene always declares them."""
    body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, GHOST_BODY)
    jaw = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, GHOST_JAW_BODY)
    if body < 0 or jaw < 0:
        raise RuntimeError(
            f"mujoco_xr: {DEFAULT_SCENE} declares no `{GHOST_BODY}` / "
            f"`{GHOST_JAW_BODY}` pair; it must <include> assets/leader/leader_gripper.xml."
        )
    return _GhostChannels(int(model.body_mocapid[body]), int(model.body_mocapid[jaw]))


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

    The inverse of `_mujoco_xr.mj_from_xr_pos`, derived from the same two exported
    constants so there is still only one definition of the frame.
    """
    out = np.empty(3)
    inverse = np.empty(4)
    mujoco.mju_negQuat(inverse, np.array(_mujoco_xr.QUAT_MJ_FROM_XR, dtype=float))
    mujoco.mju_rotVecQuat(
        out,
        np.asarray(p_mj, dtype=float) - np.array(_mujoco_xr.TRANS_MJ_FROM_XR),
        inverse,
    )
    return out


def _xr_from_mj_quat(q_wxyz: np.ndarray) -> np.ndarray:
    """MuJoCo world orientation (wxyz) -> XR orientation as xyzw."""
    inverse = np.empty(4)
    mujoco.mju_negQuat(inverse, np.array(_mujoco_xr.QUAT_MJ_FROM_XR, dtype=float))
    q_xr = np.empty(4)
    mujoco.mju_mulQuat(q_xr, inverse, np.asarray(q_wxyz, dtype=float))
    return np.array([q_xr[1], q_xr[2], q_xr[3], q_xr[0]])


def ghost_body_from_pose(pose: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A 7-D XR hand pose -> where the leader ghost BODY goes in MuJoCo world.

    The grip calibration lives on this side of the boundary, so follower.py never owns
    it. _QUAT_HAND_FROM_GHOST right-multiplies because it is fixed in the gripper's
    frame; left-multiplying swings the ghost around the room as the operator turns.
    """
    p_xr = [float(pose[0]), float(pose[1]), float(pose[2])]
    q_xyzw = [float(pose[3]), float(pose[4]), float(pose[5]), float(pose[6])]

    q_grip = np.array(_mujoco_xr.mj_from_xr_quat(q_xyzw), dtype=float)
    p_grip = np.array(_mujoco_xr.mj_from_xr_pos(p_xr), dtype=float)

    q_body = np.empty(4)
    mujoco.mju_mulQuat(q_body, q_grip, _QUAT_HAND_FROM_GHOST)
    p_offset = np.empty(3)
    mujoco.mju_rotVecQuat(p_offset, _POS_HAND_FROM_GHOST, q_grip)
    return p_grip + p_offset, q_body


def _grip_quat_mj(q_body: np.ndarray) -> np.ndarray:
    """The MuJoCo grip orientation (wxyz) whose ghost body lands at ``q_body``."""
    inverse = np.empty(4)
    mujoco.mju_negQuat(inverse, _QUAT_HAND_FROM_GHOST)
    q_grip = np.empty(4)
    mujoco.mju_mulQuat(q_grip, np.asarray(q_body, dtype=float), inverse)
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
    p_offset = np.empty(3)
    mujoco.mju_rotVecQuat(p_offset, _POS_HAND_FROM_GHOST, q_grip)

    transform = np.eye(4)
    transform[:3, 3] = _xr_from_mj_pos(np.asarray(p_body, dtype=float) - p_offset)
    rot = np.empty(9)
    q_xyzw = _xr_from_mj_quat(q_grip)
    mujoco.mju_quat2Mat(rot, np.array([q_xyzw[3], q_xyzw[0], q_xyzw[1], q_xyzw[2]]))
    transform[:3, :3] = rot.reshape(3, 3)
    return transform


def _update_ghost(
    data, ghost: _GhostChannels, pose: np.ndarray, closedness: float
) -> None:
    """Lock the leader gripper to the governed pose; swing its trigger.

    `pose` is the harness output, not the controller. Both arguments must be held
    frozen by the caller on an untracked frame -- (0, 0, 0) is the scene origin, and a
    jaw articulating on a frozen body reads as an actuated gripper. Writes `mocap_*`
    only; the caller owns the mj_forward.
    """
    p_body, q_body = ghost_body_from_pose(pose)

    data.mocap_pos[ghost.body] = p_body
    data.mocap_quat[ghost.body] = q_body

    # Rotated ABOUT the hinge, not placed at it: the jaw's XML rest pose equals the
    # ghost's, so the pivot lives in exactly one place.
    angle = _TRIGGER_RELEASED_RAD + closedness * (
        _TRIGGER_SQUEEZED_RAD - _TRIGGER_RELEASED_RAD
    )
    q_hinge = np.empty(4)
    mujoco.mju_axisAngle2Quat(q_hinge, _TRIGGER_HINGE_AXIS, angle)
    q_jaw = np.empty(4)
    mujoco.mju_mulQuat(q_jaw, q_body, q_hinge)

    # Rotating the ghost frame about the hinge maps 0 to (pivot - R_hinge.pivot).
    swung = np.empty(3)
    mujoco.mju_rotVecQuat(swung, _TRIGGER_HINGE_POS, q_hinge)
    offset = np.empty(3)
    mujoco.mju_rotVecQuat(offset, _TRIGGER_HINGE_POS - swung, q_body)

    data.mocap_pos[ghost.jaw] = p_body + offset
    data.mocap_quat[ghost.jaw] = q_jaw


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
    return follower.yaw_of_axis(q_hand_xyzw, _HAND_FORWARD_AXIS)


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
        if min(np.linalg.norm(aim), np.linalg.norm(grip)) < _MIN_QUAT_NORM:
            return False
    except (ValueError, IndexError, TypeError):
        return False

    # aim^-1 . grip, wxyz: what carries a direction from the GRIP frame into AIM's.
    inverse = np.empty(4)
    mujoco.mju_negQuat(inverse, aim[[3, 0, 1, 2]])
    aim_from_grip = np.empty(4)
    mujoco.mju_mulQuat(aim_from_grip, inverse, grip[[3, 0, 1, 2]])
    # The ghost offset is applied in the hand's frame, so carrying it across costs both
    # terms: the origins' separation pulled back into the new frame, and the old offset
    # turned by the same rotation the orientation above is. Dropping the second leaves
    # the ghost centimetres out while its orientation looks perfect.
    separation = np.empty(3)
    mujoco.mju_rotVecQuat(separation, grip_pos - aim_pos, inverse)
    turned = np.empty(3)
    mujoco.mju_rotVecQuat(
        turned, np.asarray(_POS_HAND_FROM_GHOST, dtype=float), aim_from_grip
    )
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
    inverse = np.empty(4)
    mujoco.mju_negQuat(inverse, arm.jaw_yaw_xr)
    bias = np.empty(4)
    mujoco.mju_mulQuat(bias, arm.base_yaw_xr, inverse)
    return bias


def _log_grip_posture(arm) -> tuple[float, float]:
    """Invert the chain at Q_HOME and report the posture the gate will ask for.

    Both angles are un-yawed into the operator's own frame, so they read the same
    whichever way they face -- which is also what lets this run before the anchor. Warns
    rather than raises: this app is the only place the calibration can be judged.
    """
    p_body, q_body = arm.gripper_pose_mj()
    ghost_axis = np.empty(3)
    mujoco.mju_rotVecQuat(ghost_axis, _GHOST_POINTING_AXIS, q_body)
    # The OPERATOR's frame is the HAND's yaw, which the base leads by base_yaw_bias.
    # Un-yawing by the base instead reports the demand a whole bias out, which is
    # invisible while that bias is small and wrong by 93 degrees once it is not.
    inverse_bias, hand_yaw, unyaw = np.empty(4), np.empty(4), np.empty(4)
    mujoco.mju_negQuat(inverse_bias, base_yaw_bias(arm))
    mujoco.mju_mulQuat(hand_yaw, arm.base_yaw_xr, inverse_bias)
    mujoco.mju_negQuat(unyaw, hand_yaw)

    def in_operator_frame(direction_xr):
        out = np.empty(3)
        mujoco.mju_rotVecQuat(out, np.asarray(direction_xr, dtype=float), unyaw)
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


def _frame_clock(info) -> float | None:
    """The app's clock, or None if this frame carries no time.

    viz zeroes predicted_display_time with should_render on every frame before
    kRunning. The caller must skip the sample rather than record a zero, or the next
    real frame computes dt from 0 and _clamp_dt reports a full MAX_DT_S stall.
    """
    if info.predicted_display_time == 0:
        return None
    return info.predicted_display_time / 1e9


def run() -> int:
    model = mujoco.MjModel.from_xml_path(str(DEFAULT_SCENE))
    data = mujoco.MjData(model)
    # Before the Renderer, which uploads geometry once from the model address: the
    # follower repoints geom materials and poses its joints here. Not placed yet --
    # that waits for the first head pose, in _Preview.before_step.
    arm = follower.Follower(model, data)

    # Order is load-bearing: VizSession calls xrCreateInstance, so an extension
    # discovered after it cannot be added, and a controller tracker missing
    # XR_NVX1_action_context is silently dead rather than an error. The clutch's home
    # is pushed every non-ENGAGED frame, so this constructor value only has to be
    # well-formed -- nothing can latch before the anchor exists.
    pipeline, clutch = _build_pipeline(pose_from_ghost_body(*arm.gripper_pose_mj()))
    required_extensions = get_required_oxr_extensions_from_pipeline(pipeline)

    config = viz.VizSessionConfig()
    config.mode = _DISPLAY_MODE
    config.app_name = "MuJoCoXR"
    config.xr_near_z = NEAR_Z
    config.xr_far_z = FAR_Z
    config.required_extensions = required_extensions
    # Alpha 0 = "show passthrough here", honoured at the runtime's discretion:
    # viz sets the source-alpha blend bit only for a non-opaque environment, so
    # a VR headset composites black instead, which is legible rather than broken.
    config.clear_color = (0.0, 0.0, 0.0, 0.0)

    viz_session = viz.VizSession.create(config)
    renderer = None
    gl_context = None
    try:
        resolution = viz_session.get_recommended_resolution()

        layer_config = viz.ProjectionLayerConfig()
        layer_config.name = "mujoco_scene"
        layer_config.view_resolution = resolution
        layer_config.color_format = viz.PixelFormat.kRGBA8
        layer_config.depth_format = viz.PixelFormat.kD32F
        layer_config.stereo = _VIEW_COUNT == 2
        layer = viz_session.add_projection_layer(layer_config)

        # After VizSession.create, which cudaSetDevice's the GPU behind its
        # Vulkan device; the renderer checks this context landed on that one.
        gl_context = mujoco.GLContext(resolution.width, resolution.height)
        gl_context.make_current()

        # MuJoCo resolves multisample renderbuffers only inside mjr_readPixels,
        # which this path never calls, and a multisample source cannot be
        # blitted with a y flip in one step.
        model.vis.quality.offsamples = 0

        renderer = _mujoco_xr.Renderer(
            width=resolution.width,
            height=resolution.height,
            view_count=_VIEW_COUNT,
            near_z=NEAR_Z,
            far_z=FAR_Z,
            model_address=model._address,
        )

        _log_startup(resolution, type(gl_context).__module__)

        # After the startup block, so its line reads as part of the same report.
        ghost = _resolve_ghost(model)
        LOG.info(
            "leader ghost: bound to mocap %d (body) / %d (trigger); trigger driven by "
            "SO101GripperRetargeter, %.0f deg released to %.0f deg squeezed",
            ghost.body,
            ghost.jaw,
            math.degrees(_TRIGGER_RELEASED_RAD),
            math.degrees(_TRIGGER_SQUEEZED_RAD),
        )

        arm.log_placement()
        # Before the anchor, and correct there: both angles are reported in the
        # operator's own frame, which the anchor's yaw is exactly what defines.
        _log_grip_posture(arm)

        monitor = InterventionMonitor(model)
        LOG.info(
            "harness:    the ghost renders the EePoseRateLimiter output, clamped at "
            "%.2f m/s / %.0f deg/s and rejecting above %.2f m/s / %.0f deg/s. Amber "
            "while clamping, red while rejecting, authored blue passing through.",
            _HARNESS.max_linear_velocity,
            math.degrees(_HARNESS.max_angular_velocity),
            _HARNESS.reject_linear_velocity,
            math.degrees(_HARNESS.reject_angular_velocity),
        )

        oxr = viz_session.get_oxr_handles()
        if oxr is None:
            raise RuntimeError(
                "VizSession is in kXr mode but produced no OpenXR handles; the backend did not initialize."
            )
        teleop_config = TeleopSessionConfig(
            app_name="MuJoCoXR",
            pipeline=pipeline,
            # Never pass trackers=: TeleopSession discovers them from the graph,
            # and passing them again duplicates the set.
            oxr_handles=OpenXRSessionHandles(*oxr),
        )
        with TeleopSession(teleop_config) as teleop_session:
            try:
                _loop(
                    viz_session,
                    layer,
                    renderer,
                    model,
                    data,
                    teleop_session,
                    ghost,
                    monitor,
                    arm,
                    clutch,
                )
            finally:
                LOG.info(monitor.summary())
    finally:
        # Innermost first: the renderer's GL objects need a current context.
        if renderer is not None:
            renderer.close()
        if gl_context is not None:
            gl_context.free()
        viz_session.destroy()
    return 0


# ── The per-frame protocol ─────────────────────────────────────────────────
# It spans four files, so it is stated once, here. Each frame, in order:
#
#   1. before_step()  -- anchor the arm to the head if it is not anchored yet,
#                        push the hand's position at the follower's rotation as
#                        the clutch home (every non-ENGAGED frame), and emit the
#                        permission leaf.
#   2. step()         -- the retargeting graph runs: jaw, grip source, clutch,
#                        limiter. The clutch reads permission on THIS frame.
#   3. after_step()   -- advance the phase, drive the arm, write the ghost's
#                        mocap rows, mj_forward, re-evaluate the gate.
#   4. render         -- mjv_updateScene reads geom_xpos, then submit.
#
# Permission is one frame stale, deliberately: step N's leaf carries the verdict
# after_step produced on frame N-1, because the gate needs a limiter band step N has
# not computed yet. Squeezing inside that 14 ms costs nothing -- a denied latch stays
# OWED and fires on the first permitted frame.
class _Preview:
    """The follower/leader handoff: one call before ``step()``, one after.

    Everything in ``_loop`` that is not rendering. Split out so the whole engage
    sequence can be driven headlessly at frame rate, which is the only way to exercise
    the gate's pass-through conjunct -- a quasi-static drive passes it by luck.
    """

    def __init__(self, model, data, ghost, monitor, arm, clutch) -> None:
        """Bind to one scene, one pair of tools and one clutch.

        Measures the arm's yaw bias here, while the base still stands on the yaw
        ``Follower.__init__`` left it on -- ``anchor`` has not run, so the reading is the
        arm's own and not a head's.
        """
        self._model = model
        self._data = data
        self._ghost = ghost
        self._monitor = monitor
        self._arm = arm
        self._clutch = clutch
        self._ghost_geoms = np.array(
            [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, n) for n in GHOST_GEOMS]
        )
        self.phases = follower.PhaseMachine()
        self._gate = follower.EngageGate()
        # Its own key, not the un-anchored one: they share a frame in practice, and
        # merging them would suppress the first verdict of the session.
        self.verdict = follower.GateResult((("startup", "starting up"),))
        # Neither tool is drawn until the arm is anchored, so start both hidden rather
        # than relying on the first after_step to arrive.
        follower.set_geoms_visible(model, self._ghost_geoms, False)
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
        permitted = self.phases.permits_engagement or self.verdict.ok
        return (
            {ENGAGE_PERMISSION_LEAF: {ValueInput.VALUE: _permission(permitted)}},
            ExecutionEvents(reset=reset, execution_state=ExecutionState.RUNNING),
        )

    def after_step(self, result, dt: float) -> follower.ClutchPhase:
        """Advance the phase, drive both tools, and re-evaluate the gate."""
        if not self._arm.anchored:
            # Nowhere to put the arm yet. Draw neither tool and hold the gate shut:
            # with `permits_engagement` false too, `before_step` cannot permit a latch.
            # Returns before the phase machine, so a frame with no placement is a frame
            # that did not happen.
            self._show(follower_visible=False, ghost_visible=False)
            self._blocked(follower.GateResult((("unanchored", "no head pose yet"),)))
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
        if hand is not None and (
            not np.all(np.isfinite(hand))
            or float(np.linalg.norm(hand[3:7])) < _MIN_QUAT_NORM
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

        limiter_passing = False
        if commanded is not None and governed is not None:
            # The body needs no tracking-loss gate: the clutch emits its held pose on
            # every disarm path, so the pipeline freezes it. The JAW does, hence the
            # latch above.
            _update_ghost(self._data, self._ghost, governed, self._closedness)
            # Classified on every governed frame, painted only while the ghost is the
            # tool on show: the band needs an unbroken baseline to tell a refused frame
            # from a clamped one.
            band = self._monitor.update(self._model, commanded, governed, paint=engaged)
            limiter_passing = band is HarnessBand.PASS_THROUGH

        # The module docstring's invariant, at the one place that writes mocap_*.
        # Unconditional, and here rather than in _loop so the tests drive it: without
        # it the gate's xpos read below and mjv_updateScene both see the ghost's XML
        # rest pose, and the leader appears in the right place and never moves again.
        mujoco.mj_forward(self._model, self._data)

        self._blocked(
            self._gate.evaluate(
                phase=phase,
                hand_quat_xyzw=None if hand is None else hand[3:7],
                home_quat_xyzw=grip_quat_from_ghost_body(
                    self._arm.gripper_pose_mj()[1]
                ),
                limiter_passing=limiter_passing,
                dt=dt,
            )
        )
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
        trim = np.empty(4)
        mujoco.mju_axisAngle2Quat(
            trim, np.array([0.0, 1.0, 0.0]), math.radians(self._yaw_trim_deg)
        )
        biased = np.empty(4)
        mujoco.mju_mulQuat(biased, facing, self._yaw_bias)
        base_yaw = np.empty(4)
        mujoco.mju_mulQuat(base_yaw, biased, trim)
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
        follower.set_geoms_visible(self._model, self._ghost_geoms, ghost_visible)

    def _blocked(self, verdict: follower.GateResult) -> None:
        """Publish the gate's verdict: the arm's colour, and a log on transitions.

        Keyed on `verdict.keys`, never on the text it renders. The verdict is stored
        even on frames nothing is logged, so the first frame after a release is
        compared against the last engaged one and the release is always heard.
        """
        previous_keys = self.verdict.keys
        self.verdict = verdict
        self._arm.set_engageable(verdict.ok)
        if verdict.keys == previous_keys or follower.GATE_KEY_ENGAGED in verdict.keys:
            return
        LOG.info(
            "clutch: %s",
            "engageable"
            if verdict.ok
            else "blocked (" + "; ".join(verdict.blocked) + ")",
        )


def _loop(
    viz_session,
    layer,
    renderer,
    model,
    data,
    teleop_session,
    ghost,
    monitor,
    arm,
    clutch,
) -> None:
    view_count = renderer.view_count
    checked_frustum = False
    preview = _Preview(model, data, ghost, monitor, arm, clutch)
    previous_clock: float | None = None

    while not viz_session.should_close():
        info = viz_session.begin_frame()
        try:
            # Nothing integrates, so there is no fixed-step accumulator and the whole
            # frame hangs off should_render. That is also what keeps
            # teleop_session.step() from calling xrSyncActions on the unthrottled
            # pre-kRunning burst. The cost is that retargeter compute follows render
            # cadence; a resumed session sees one large dt, bounded by max_dt.
            if not info.should_render:
                continue

            now = _frame_clock(info)
            dt = (
                0.0
                if now is None or previous_clock is None
                else _clamp_dt(now - previous_clock)
            )
            previous_clock = previous_clock if now is None else now

            # Input first, so it precedes everything it feeds. The head pose comes
            # from this frame's views, which viz only fills past should_render.
            external_inputs, events = preview.before_step(_head_pose(info))
            result = teleop_session.step(
                external_inputs=external_inputs, execution_events=events
            )
            preview.after_step(result, dt)

            renderer.update_scene(model._address, data._address)
            # mjv_updateScene truncates on overflow and returns normally, with
            # only a stderr warning nobody reads in a frame loop.
            if renderer.ngeom >= renderer.maxgeom:
                raise RuntimeError(
                    f"mjvScene is full: ngeom={renderer.ngeom} maxgeom={renderer.maxgeom}. "
                    "Geometry is being dropped -- raise kMaxGeom in "
                    "cpp/scene_renderer.cpp."
                )

            # No view-count check here: render() sees the flattened lengths and
            # rejects a mismatch in those terms.
            poses, fovs = _flatten_xr_views(info)
            renderer.render(poses, fovs)

            # First rendered frame only: the fov changes per frame, the
            # convention does not.
            if not checked_frustum:
                for view in range(view_count):
                    _assert_frustum(
                        renderer.frustum(view), info.views[view].fov, NEAR_Z, FAR_Z
                    )
                LOG.info(
                    "frustum verified on the first rendered frame (matches FrameInfo fov, clip planes agree "
                    "with VizSessionConfig)"
                )
                checked_frustum = True

            layer.submit(
                renderer.color(0),
                renderer.depth(0),
                renderer.color(1),
                renderer.depth(1),
            )
        finally:
            # Follows EVERY begin_frame(), including the should_render == False
            # path and any exception above. Skipping it wedges the frame loop.
            viz_session.end_frame()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--verbose", action="store_true", help="Debug-level logging.")
    CloudXRLauncher.add_launcher_arguments(parser)
    args = parser.parse_args(argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[mujoco_xr] %(message)s",
    )

    # Before launch_context starts the runtime, so an unfetched checkout says so
    # plainly rather than buried in the runtime's startup logging.
    missing = _missing_assets()
    if missing:
        raise SystemExit(
            f"mujoco_xr: the SO-101 assets are not fetched ({', '.join(missing)}).\n"
            f"  Run {FETCH_SCRIPT} from the repository root, then reinstall:\n"
            "  uv pip install --reinstall-package isaacteleop-examples-mujoco-xr "
            "./examples/mujoco_xr"
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
