# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A MuJoCo scene drawn into a Televiz XR session.

One OpenXR session shared between VizSession (rendering) and TeleopSession
(input); the scene is drawn by Vulkan into images viz owns and reaches
ProjectionLayer.submit() by CUDA pointer, never through host memory.

    VizSession(kXr)  ──get_oxr_handles()──▶  TeleopSession
         │                                        │
         │ vk_device / vk_physical_device         │ EePoseRateLimiter output
         ▼                                        ▼                      │
    _mujoco_xr.Renderer  ──__cuda_array_interface__──▶  ProjectionLayer  │
         ▲                                                               │
         └──────────────── mjData.mocap_pos/_quat ◀─────────────────────┘

C++ owns mjvScene/mjvOption/mjvCamera; Python owns mjModel/mjData/mj_step, so
everything reading a controller and writing mjData is testable without a GPU.

The ghost renders the safety harness's output rather than the controller, so
what the operator sees is the command a follower would execute. It lags the hand
and changes colour while the harness intervenes -- see harness.py.

Frame order is load-bearing: input is sampled before the physics it feeds, on
every frame that will step or draw.
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
from isaacteleop.retargeting_engine.interface import OutputCombiner
from isaacteleop.retargeters.rate_limiter import (
    EE_POSE_KEY,
    EePoseRateLimiter,
    RateLimiterConfig,
)
from isaacteleop.retargeters.SO101.gripper_retargeter import (
    GRIPPER_COMMAND_KEY,
    SO101GripperRetargeter,
)
from isaacteleop.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig,
    get_required_oxr_extensions_from_pipeline,
)

from . import _mujoco_xr
from .harness import GripPoseSource, InterventionMonitor

LOG = logging.getLogger("mujoco_xr")

# The only clip planes in the app. VizSessionConfig, the renderer's projection
# and the submitted depth must all agree; drift makes world-locked geometry
# swim under head motion, visible only on a headset. No near/far literal exists
# in cpp/, by construction.
NEAR_Z = 0.05
FAR_Z = 50.0

# Wall-clock ceiling for one simulation advance. See _clamp_dt.
MAX_DT_S = 0.1

# kXr is the only mode: this app needs a headset and a CloudXR runtime. A
# headless fallback should arrive with the CI job that runs it
# (NVIDIA/IsaacTeleop#880), not before.
_DISPLAY_MODE = viz.DisplayMode.kXr

# Stereo, always. layer.submit() in _loop is spelled out per eye and cannot read
# this name, so changing it means editing that call too.
_VIEW_COUNT = 2

_CLOCK_SOURCE = (
    "FrameInfo.predicted_display_time; frames with no prediction are skipped, "
    "not sampled as 0"
)

# Package data, so it resolves identically from the wheel and the source tree.
# Must stay absolute: scene.xml <include>s a fragment in a subdirectory, and on
# mujoco 3.11.0 a relative model path mis-composes that fragment's mesh paths
# and fails naming a file that is right there on disk.
DEFAULT_SCENE = Path(__file__).parent / "assets" / "scene.xml"

# The meshes scene.xml <include>s, fetched rather than vendored (see
# scripts/fetch-so-arm.sh). Checked by name before MuJoCo sees the scene, because
# MjModel.from_xml_path's failure for a missing <include> target is a bare
# "Error opening file <mesh>.stl" naming a file nobody asked for.
FETCH_SCRIPT = "examples/mujoco_xr/scripts/fetch-so-arm.sh"
_LEADER_ASSETS = Path(__file__).parent / "assets" / "leader"
_LEADER_MESHES = (
    "Wrist_Roll_SO101.stl",
    "Trigger_SO101.stl",
    "Handle_SO101.stl",
    "STS3215_03a.stl",
)


def _missing_leader_assets() -> list[str]:
    """Names of the fetched meshes that are not on disk. Empty when fetched."""
    return [n for n in _LEADER_MESHES if not (_LEADER_ASSETS / n).is_file()]


# One hand and no flag: the ghost is a right-handed leader gripper, and the left
# controller draws nothing.
GHOST_HAND = ControllersSource.RIGHT

# The two mocap bodies leader_gripper.xml declares.
GHOST_BODY = "leader_ghost"
GHOST_JAW_BODY = "leader_ghost_jaw"

# The limiter's input, carried alongside its output under a name of this app's
# choosing. Nothing draws it; it is the reference the band is measured against.
RAW_POSE_KEY = "raw_ee_pose"

# ── Where the ghost sits on the hand ───────────────────────────────────────
# Measured on a headset, not derived: this is a claim about a hand holding a
# CONTROLLER, so do not re-derive it from the mesh -- a model assuming the hand
# passes through the handle loop puts the loop centroid 56 mm from the palm.
#
# Euler degrees, intrinsic XYZ, i.e. MuJoCo's `euler=` (pinned by a test). To
# re-tune, change one angle and reinstall: Rz spins the gripper about its long
# axis, Rx/Ry tilt it, _POS_GRIP_FROM_GHOST slides it along the grip axes
# (-Z little finger -> thumb, +X into the palm, +Y through the knuckles). No
# test asserts a posture, so re-tuning cannot turn them red.
_EULER_GRIP_FROM_GHOST_DEG = (60, 180, 270)
_POS_GRIP_FROM_GHOST = np.array((0, 0.02, -0.025))

# ── The trigger hinge ──────────────────────────────────────────────────────
# The follower's `gripper` revolute joint, from SO-ARM100's
# so101_new_calib.urdf: origin xyz="0.0202 0.0188 -0.0234" rpy="1.5708 0 0",
# axis "0 0 1". The right source even for the LEADER's trigger, which is
# mounted in the follower's moving-jaw slot and shares the hinge. The axis
# below is that "0 0 1" carried through the joint frame's 90-degree roll.
#
# Do not re-derive either from the meshes: a pivot from the nearest
# trigger-to-shank vertex pair and an axis from the grip frame both look right
# at the joint's zero and are wrong by the far end of its travel.
_TRIGGER_HINGE_POS = np.array((0.0202, 0.0188, -0.0234))  # metres, ghost frame
_TRIGGER_HINGE_AXIS = np.array((0.0, -1.0, 0.0))  # unit, ghost frame

# The travel is the URDF joint's own: `upper="1.74533"` is 100.0 degrees, and
# squeezed is its authored zero. A released end short of that does not read as
# an OPEN gripper on a headset, which is the only place this can be judged.
# Do not extend to the joint's lower limit (-10 deg): that end swings the lever
# 0.4 mm into the servo. The tightest pass across 0..100 is 2.1 mm, at the
# squeezed end.
_TRIGGER_RELEASED_RAD = math.radians(100.0)  # closedness 0, jaw wide open
_TRIGGER_SQUEEZED_RAD = 0.0  # closedness 1, tucked to the authored pose


def _quat_from_euler_deg(angles_deg) -> np.ndarray:
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


# ── Derived below; nothing from here on is authored ────────────────────────
_QUAT_GRIP_FROM_GHOST = _quat_from_euler_deg(_EULER_GRIP_FROM_GHOST_DEG)


def _clamp_dt(dt: float) -> float:
    """NaN-safe clamp into [0, MAX_DT_S].

    Spelled as comparisons, not min/max: max(nan, 0) is nan, so the obvious
    form passes NaN through both limits and into mj_step.
    """
    if dt > 0:
        return MAX_DT_S if dt > MAX_DT_S else dt
    return 0.0


# ── What the harness lets through ──────────────────────────────────────────
# Chosen for this demo, not measured against a follower: ordinary reaching
# should pass through untouched, and a deliberate flick should trip the clamp
# and then the reject band, so both interventions can be provoked on demand.
# An SO-101's own envelope is lower -- RateLimiterConfig defaults to 0.25 m/s.
#
# max_dt is left at the config default, which is MAX_DT_S: a stalled frame
# authorizes the same bounded step here as it does in the physics.
_HARNESS = RateLimiterConfig(
    max_linear_velocity=0.5,  # m/s
    max_angular_velocity=2.5,  # rad/s, ~143 deg/s
    reject_linear_velocity=2.0,  # m/s
    reject_angular_velocity=10.0,  # rad/s
)


def _build_pipeline() -> OutputCombiner:
    """Controllers, the shipped SO-101 jaw retargeter, and the pose harness.

    Both retargeters are BaseRetargeter nodes in the pipeline rather than library
    calls beside it. The shipped scene has no robot, so the jaw the retargeter
    drives is the operator's own trigger; the SO-101 arrives with the scene
    catalogue and reads the same outputs.

    The ghost renders the limiter's output, so what the operator sees is the
    command a follower would execute rather than where their hand is. The raw
    controller stays in the combiner beside it -- not to be drawn, but because
    comparing the two is how harness.InterventionMonitor recovers which band the
    limiter is in.

    SO101ClutchRetargeter is the shipped producer of this `ee_pose` contract and
    is deliberately not used: it re-bases the pose onto a follower's base frame
    at every engage, and this ghost is a leader in the operator's hand, which has
    no home to clutch to.

    The jaw is ungoverned. A JointRateLimiter would bound it, but the trigger is
    one scalar the operator drives directly, not an IK output that can diverge.
    """
    controllers = ControllersSource(name="controllers")
    jaw = SO101GripperRetargeter(name="ghost_jaw", input_device=GHOST_HAND).connect(
        {GHOST_HAND: controllers.output(GHOST_HAND)}
    )
    grip = GripPoseSource(name="ghost_grip", input_device=GHOST_HAND).connect(
        {GHOST_HAND: controllers.output(GHOST_HAND)}
    )
    governed = EePoseRateLimiter(name="ghost_harness", config=_HARNESS).connect(
        {EE_POSE_KEY: grip.output(EE_POSE_KEY)}
    )
    return OutputCombiner(
        {
            ControllersSource.LEFT: controllers.output(ControllersSource.LEFT),
            ControllersSource.RIGHT: controllers.output(ControllersSource.RIGHT),
            GRIPPER_COMMAND_KEY: jaw.output(GRIPPER_COMMAND_KEY),
            RAW_POSE_KEY: grip.output(EE_POSE_KEY),
            EE_POSE_KEY: governed.output(EE_POSE_KEY),
        }
    )


def _flatten_xr_views(info) -> tuple[list[float], list[float]]:
    """FrameInfo.views -> the flat float arrays the renderer takes.

    Filled field by field, never sliced: viz.Pose3D.orientation is (w,x,y,z)
    and a controller's GRIP_ORIENTATION is (x,y,z,w).
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


def _assert_projection(p: list[float], near: float, far: float) -> None:
    """Per-frame, because the projection is rebuilt from per-frame fov.

    `p` is column-major. Depth is asserted as the shipped contract
    (near -> 0, far -> 1); two viz doc comments claim reverse-Z, the code is
    standard Z.
    """
    p00, p11, p23 = p[0], p[5], p[11]
    assert p00 > 0.0, (
        f"P[0][0]={p00}: left/right swapped, or a zeroed Fov reached the projection"
    )
    # The load-bearing one: b = n*tan(angleUp) > 0 and t = n*tan(angleDown) < 0
    # give 2n/(t-b) < 0. That negative is the Y flip, which drives triangle
    # winding -- a depth-range check touches only P[2][2] / P[2][3] / P[3][2]
    # and would not notice it going positive.
    assert p11 < 0.0, (
        f"P[1][1]={p11}: the angleUp->bottom Y flip is gone; winding will invert"
    )
    assert abs(p23 + 1.0) < 1e-6, f"P[2][3]={p23}: not a standard perspective divide"

    # Asserted as the contract we ship rather than as somebody else's formula,
    # so it survives a viz refactor.
    for z_view, expected in ((-near, 0.0), (-far, 1.0)):
        clip_z = p[10] * z_view + p[14]
        clip_w = p[11] * z_view + p[15]
        assert abs(clip_z / clip_w - expected) < 1e-4, (
            f"depth encoding broken: z_view={z_view} maps to {clip_z / clip_w}, expected {expected}"
        )


def _log_startup(resolution) -> None:
    """One block naming every assumption that is invisible at runtime."""
    try:
        version = importlib.metadata.version("isaacteleop")
    except importlib.metadata.PackageNotFoundError:
        version = "<not installed as a distribution>"
    trans = _mujoco_xr.TRANS_MJ_FROM_XR

    LOG.info("scene:      %s", DEFAULT_SCENE)
    # Cross-example venv collisions are real: several examples here ship their
    # own .venv, and picking up the wrong isaacteleop is invisible otherwise.
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
        "clip:       near=%.4f far=%.2f (one pair -> VizSessionConfig, projection, submitted depth)",
        NEAR_Z,
        FAR_Z,
    )
    LOG.info(
        "frames:     mj_from_xr translation = (%.3f, %.3f, %.3f) m. x is operator standoff; z is a FLOOR datum, "
        "which the session's reference space does not currently establish -- see cpp/frames.hpp. Neither term may "
        "be zeroed.",
        trans[0],
        trans[1],
        trans[2],
    )
    LOG.info("clock:      %s", _CLOCK_SOURCE)
    LOG.info(
        "depth submission: requested (ProjectionLayer depth_format=D32F). Whether the runtime ACCEPTED it is "
        "not queryable -- XrBackend::depth_layer_enabled_ is private with no accessor or binding. The absence "
        "of errors is NOT confirmation."
    )


class _GhostChannels(NamedTuple):
    """The two mocap rows the ghost writes, resolved once at startup.

    Mocap indices, not body ids: mocap_pos/mocap_quat are indexed by
    body_mocapid, and a body id there writes into another body's row.
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
    """One of the pipeline's 7-D pose channels, or None when it carries nothing.

    Carrying nothing has two spellings here and `is_none` is only one of them.
    RAW_POSE_KEY is an Optional group, so it goes absent on every untracked
    frame and `is_none` says so. EE_POSE_KEY is NOT optional -- the limiter
    declares it required, TensorGroup.is_none is therefore hardcoded False, and
    the group reads as present from the very first frame while the tensor inside
    it stays UNSET until the limiter has had a valid grip to latch. Every
    session starts there: the grip pose is not localizable for the first frames,
    so the limiter is handed nothing and writes nothing.

    Reading an unset tensor raises, and Tensor exposes no "has it been set"
    predicate, so that raise is the only signal available.
    """
    pose = result[key]
    if pose.is_none:
        return None
    try:
        tensor = pose[0]
    except ValueError:
        return None
    return np.asarray(np.from_dlpack(tensor), dtype=float)


def _update_ghost(data, ghost: _GhostChannels, pose: np.ndarray, result) -> None:
    """Lock the leader gripper to the governed pose; swing its trigger.

    `pose` is the harness output, not the controller: what the ghost shows is the
    command a follower would execute. The caller's None gate is the same one that
    used to live here -- an untracked controller leaves the grip pose at (0, 0, 0),
    which is the MuJoCo scene origin and a place a legitimate pose could put it.
    Freezing where it was last seen is the honest rendering of "tracking lost", so
    there is no else branch.

    _QUAT_GRIP_FROM_GHOST right-multiplies because it is fixed in the gripper's
    own frame; left-multiplying swings the ghost around the room as the operator
    turns.
    """
    p_xr = [float(pose[0]), float(pose[1]), float(pose[2])]
    q_xyzw = [float(pose[3]), float(pose[4]), float(pose[5]), float(pose[6])]

    q_grip = np.array(_mujoco_xr.mj_from_xr_quat(q_xyzw), dtype=float)
    p_grip = np.array(_mujoco_xr.mj_from_xr_pos(p_xr), dtype=float)

    q_body = np.empty(4)
    mujoco.mju_mulQuat(q_body, q_grip, _QUAT_GRIP_FROM_GHOST)
    p_offset = np.empty(3)
    mujoco.mju_rotVecQuat(p_offset, _POS_GRIP_FROM_GHOST, q_grip)
    p_body = p_grip + p_offset

    data.mocap_pos[ghost.body] = p_body
    data.mocap_quat[ghost.body] = q_body

    # Closedness comes through the pipeline output, so the deadzone and clamp
    # are the retargeter's contract rather than this app's. Rotated ABOUT the
    # hinge, not placed at it: the jaw body's XML rest pose equals the ghost's,
    # so the pivot lives in exactly one place.
    closedness = float(result[GRIPPER_COMMAND_KEY][0])
    angle = _TRIGGER_RELEASED_RAD + closedness * (
        _TRIGGER_SQUEEZED_RAD - _TRIGGER_RELEASED_RAD
    )
    q_hinge = np.empty(4)
    mujoco.mju_axisAngle2Quat(q_hinge, _TRIGGER_HINGE_AXIS, angle)
    q_jaw = np.empty(4)
    mujoco.mju_mulQuat(q_jaw, q_body, q_hinge)

    # Where the jaw body's origin lands: rotating the ghost frame about the
    # hinge maps 0 to (pivot - R_hinge . pivot).
    swung = np.empty(3)
    mujoco.mju_rotVecQuat(swung, _TRIGGER_HINGE_POS, q_hinge)
    offset = np.empty(3)
    mujoco.mju_rotVecQuat(offset, _TRIGGER_HINGE_POS - swung, q_body)

    data.mocap_pos[ghost.jaw] = p_body + offset
    data.mocap_quat[ghost.jaw] = q_jaw


def _frame_clock(info) -> float | None:
    """The simulation clock, or None if this frame carries no time.

    viz zeroes predicted_display_time together with should_render on every
    frame before kRunning. Sampling it would make the next real frame compute
    dt from 0 and step 50 times inside one display frame. The caller must skip
    the sample and leave the accumulator alone.
    """
    if info.predicted_display_time == 0:
        return None
    return info.predicted_display_time / 1e9


def run() -> int:
    model = mujoco.MjModel.from_xml_path(str(DEFAULT_SCENE))
    data = mujoco.MjData(model)

    # Order is load-bearing: build the pipeline, aggregate the OpenXR extensions
    # its trackers need, put them on the VizSessionConfig, and only then create
    # the session. VizSession calls xrCreateInstance, so an extension discovered
    # later cannot be added -- and a controller tracker without
    # XR_NVX1_action_context is silently dead rather than an error.
    pipeline = _build_pipeline()
    required_extensions = get_required_oxr_extensions_from_pipeline(pipeline)

    config = viz.VizSessionConfig()
    config.mode = _DISPLAY_MODE
    config.app_name = "MuJoCoXR"
    config.xr_near_z = NEAR_Z
    config.xr_far_z = FAR_Z
    config.required_extensions = required_extensions
    # Alpha 0 = "show passthrough here". Whether it is honoured is the
    # runtime's call: viz only sets the source-alpha blend bit for a non-opaque
    # environment, so a VR headset composites black instead. Accepted -- this
    # example targets passthrough, and black is legible rather than broken.
    config.clear_color = (0.0, 0.0, 0.0, 0.0)

    viz_session = viz.VizSession.create(config)
    renderer = None
    try:
        resolution = viz_session.get_recommended_resolution()

        layer_config = viz.ProjectionLayerConfig()
        layer_config.name = "mujoco_scene"
        layer_config.view_resolution = resolution
        layer_config.color_format = viz.PixelFormat.kRGBA8
        layer_config.depth_format = viz.PixelFormat.kD32F
        layer_config.stereo = _VIEW_COUNT == 2
        layer = viz_session.add_projection_layer(layer_config)

        renderer = _mujoco_xr.Renderer(
            vk_physical_device=viz_session.vk_physical_device,
            vk_device=viz_session.vk_device,
            vk_queue_family_index=viz_session.vk_queue_family_index,
            width=resolution.width,
            height=resolution.height,
            view_count=_VIEW_COUNT,
            near_z=NEAR_Z,
            far_z=FAR_Z,
            model_address=model._address,
        )

        _log_startup(resolution)

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

        monitor = InterventionMonitor(model)
        LOG.info(
            "harness:    the ghost renders the EePoseRateLimiter output, clamped at "
            "%.2f m/s / %.0f deg/s and rejecting above %.2f m/s / %.0f deg/s. It turns "
            "amber while clamping and red while rejecting; below the clamp it passes "
            "through untouched and the colour does not change.",
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
            # Never pass trackers=: TeleopSession discovers them from the
            # pipeline graph, and passing them again duplicates the set.
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
                )
            finally:
                LOG.info(monitor.summary())
    finally:
        # The renderer borrows viz_session's device: it must go first.
        if renderer is not None:
            renderer.close()
        viz_session.destroy()
    return 0


def _loop(
    viz_session, layer, renderer, model, data, teleop_session, ghost, monitor
) -> None:
    view_count = renderer.view_count
    previous_clock: float | None = None
    # Fixed-step accumulator. NOT reset or drained on a non-render frame: the
    # simulation owes that time regardless of whether anything was displayed.
    accumulator = 0.0
    checked_projection = False

    while not viz_session.should_close():
        info = viz_session.begin_frame()
        try:
            # None means "this frame carries no usable timestamp" -- skip the
            # sample entirely rather than recording a zero. See _frame_clock.
            now = _frame_clock(info)
            if now is not None:
                if previous_clock is not None:
                    accumulator += _clamp_dt(now - previous_clock)
                previous_clock = now

            # Input above the should_render gate and above the step loop, so
            # it precedes the physics it feeds. Gated on "will step or will
            # draw" rather than every frame: an ungated teleop_session.step()
            # calls xrSyncActions on the unthrottled pre-kRunning burst, which
            # is hundreds of frames in milliseconds.
            result = None
            will_step = accumulator >= model.opt.timestep
            if will_step or info.should_render:
                result = teleop_session.step()
                # Both, and both gates are load-bearing. An absent RAW_POSE_KEY
                # is tracking loss, and then the WHOLE gripper freezes -- the
                # limiter would happily hold a pose for the body while the jaw
                # kept following the trigger, which articulates the ghost on a
                # stale pose. An absent EE_POSE_KEY is the limiter with nothing
                # to emit yet.
                raw = _pose(result, RAW_POSE_KEY)
                governed = _pose(result, EE_POSE_KEY)
                if raw is not None and governed is not None:
                    _update_ghost(data, ghost, governed, result)
                    # After the ghost is placed, so the colour and the pose
                    # describe the same frame. Recolouring writes mjModel,
                    # which update_scene below picks up.
                    monitor.update(model, raw, governed)

            steps = 0
            while accumulator >= model.opt.timestep and steps < 64:
                mujoco.mj_step(model, data)
                accumulator -= model.opt.timestep
                steps += 1

            if not info.should_render:
                # Skip the draw. Deliberately do NOT touch the accumulator.
                continue

            renderer.update_scene(model._address, data._address)
            # The only check on mjv_updateScene filling mjvScene. Measured on
            # mujoco 3.11.0: it prints "WARNING: Pre-allocated visual geom
            # buffer is full" on stderr, truncates, and returns normally with
            # ngeom == maxgeom, and nobody reads a warning line in a frame loop.
            if renderer.ngeom >= renderer.maxgeom:
                raise RuntimeError(
                    f"mjvScene is full: ngeom={renderer.ngeom} maxgeom={renderer.maxgeom}. "
                    "Geometry is being dropped -- raise kMaxGeom in "
                    "cpp/scene_renderer.cpp."
                )

            # A view-count mismatch is rejected by render() below, which sees
            # the flattened lengths and says so in those terms. There is
            # deliberately no second check here.
            poses, fovs = _flatten_xr_views(info)
            renderer.render(poses, fovs)

            # First rendered frame only: the fov changes per frame but the clip
            # convention does not, and tests/test_projection.py pins it headless.
            if not checked_projection:
                for view in range(view_count):
                    _assert_projection(renderer.projection(view), NEAR_Z, FAR_Z)
                LOG.info(
                    "projection convention verified on the first rendered frame (P[1][1] < 0, near->0, far->1)"
                )
                checked_projection = True

            layer.submit(
                renderer.color(0),
                renderer.depth(0),
                renderer.color(1),
                renderer.depth(1),
            )
        finally:
            # end_frame() follows EVERY begin_frame(), including the
            # should_render == False path and any exception above. Skipping it
            # wedges the frame loop.
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

    # Before launch_context, which starts a runtime process on entry and tears
    # it down on exit: checked here, an unfetched checkout says so plainly
    # instead of landing buried in the runtime's own startup logging.
    missing = _missing_leader_assets()
    if missing:
        raise SystemExit(
            f"mujoco_xr: the leader gripper meshes are not fetched ({', '.join(missing)}).\n"
            f"  Run {FETCH_SCRIPT} from the repository root, then reinstall:\n"
            "  uv pip install --reinstall-package isaacteleop-examples-mujoco-xr "
            "./examples/mujoco_xr"
        )

    with CloudXRLauncher.launch_context(args) as launcher:
        if launcher is not None:
            LOG.info("CloudXR runtime started (WSS log: %s)", launcher.wss_log_path)
        try:
            return run()
        except KeyboardInterrupt:
            LOG.info("interrupted")
            return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
