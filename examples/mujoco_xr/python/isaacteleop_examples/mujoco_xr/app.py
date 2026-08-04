# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MuJoCo scene teleoperated from a Televiz XR session.

Single process, single thread, one OpenXR session:

    VizSession(kXr)  ──get_oxr_handles()──▶  TeleopSession
         │                                        │
         │ vk_device / vk_physical_device         │ controller grip poses
         ▼                                        ▼                      │
    _mujoco_xr.Renderer  ──__cuda_array_interface__──▶  ProjectionLayer  │
         ▲                                                               │
         └──────── mjData ◀──── teleop.Teleop (clutch + DLS IK) ◀────────┘

WHERE THE LINE BETWEEN THE LANGUAGES IS, because it is not arbitrary:
``cpp/scene_renderer.hpp`` owns ``mjvScene`` / ``mjvOption`` / ``mjvCamera``,
and Python owns ``mjModel`` / ``mjData`` / ``mj_step``. Control writes
``d.ctrl``, so control is Python -- which also makes the whole of it testable
with no GPU, no headset and no runtime (``tests/test_teleop.py``).

FRAME ORDER IS LOAD-BEARING and is not the order this file originally had:

    sample input -> clutch -> IK -> write ctrl -> mj_step xN -> render gate
    -> compose -> render -> submit

Control runs BEFORE the physics it commands, and on EVERY frame rather than
only on rendered ones. Sampling after the ``should_render`` gate was harmless
while the controller poses were only markers; once they drive ``d.ctrl`` it
means physics advancing open-loop on every non-rendered frame.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import logging
import math
import sys
import time
from pathlib import Path

import mujoco

from isaacteleop import viz
from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.oxr import OpenXRSessionHandles
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import OutputCombiner
from isaacteleop.retargeting_engine.tensor_types import ControllerInputIndex
from isaacteleop.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig,
    get_required_oxr_extensions_from_pipeline,
)

from . import _mujoco_xr, robot_spec, teleop

LOG = logging.getLogger("mujoco_xr")

# ── The single near/far pair ───────────────────────────────────────────────
# These two names are the ONLY definition of the clip planes in the app. They
# reach all three places that must agree:
#   1. VizSessionConfig.xr_near_z / .xr_far_z, which viz chains into
#      XrCompositionLayerDepthInfoKHR.nearZ / .farZ;
#   2. the renderer's projection (Renderer(near_z=..., far_z=...));
#   3. therefore the depth values in the buffer we submit.
# If (1) and (2) ever drift, the depth buffer is inconsistent with the range
# the runtime was told, compositor reprojection is wrong, and the symptom is
# world-locked geometry SWIMMING under head motion -- visible only on a
# headset. There is no near/far literal in cpp/, by construction.
#
# 0.05 / 50.0 rather than viz's default far of 100.0: this is a tabletop
# scene, and 100 m wastes depth precision where it is actually needed.
NEAR_Z = 0.05
FAR_Z = 50.0

# Wall-clock ceiling for one simulation advance. See _clamp_dt.
MAX_DT_S = 0.1

# Consecutive RENDERED frames with a frozen clock before the watchdog speaks.
# Carried over verbatim from the reference implementation
# (MuJoCoXR/src/sim_scene.cc:105). See _clock_stall_streak.
STALL_FRAMES = 11

# THE ONLY DISPLAY MODE. This app runs in kXr and nowhere else: it needs a
# headset and a CloudXR runtime, and there is deliberately no desktop or
# headless fallback. viz offers kWindow and kOffscreen, and both were once
# reachable here through a --mode flag; they were removed because neither ever
# ran anything a user wanted. kWindow never worked on any machine anyone
# checked, and kOffscreen rendered into memory and displayed nothing, so its
# only role was as a hand-run smoke test that no CI job ever executed (see
# NVIDIA/IsaacTeleop#880 -- examples have no test infrastructure to run it in).
#
# What their removal bought: no fabricated debug camera, one clock instead of
# two, an unconditional view_count, and a run() with no branch that builds
# everything except the TeleopSession. If a headless path is ever wanted again,
# it should arrive with the CI job that runs it, not before.
_DISPLAY_MODE = viz.DisplayMode.kXr

# Stereo, always: kXr is the only mode, and it has two eyes. Three places depend
# on this being 2 -- the Renderer, ProjectionLayerConfig.stereo, and the
# four-argument layer.submit() in _loop, which is spelled out per eye rather than
# built in a loop. The first two read this name; the submit call cannot, so
# changing this constant means editing that call too.
_VIEW_COUNT = 2

# The simulation clock, in two spellings of one fact: the short name is what the
# stall watchdog names in an error line, the long one is what the startup block
# prints. The second is DERIVED from the first so they cannot drift -- they used
# to be produced together by one conditional, for the same reason.
_CLOCK_NAME = "FrameInfo.predicted_display_time"
_CLOCK_SOURCE = (
    f"{_CLOCK_NAME}; frames with no prediction are skipped, not sampled as 0"
)

# PACKAGE DATA, resolved from inside the package -- one `.parent`, not three.
#
# It used to walk three parents up to examples/mujoco_xr/assets/, which was
# correct only in the old install tree. From
# site-packages/isaacteleop_examples/mujoco_xr/app.py that same walk points
# outside site-packages entirely, at a path that does not exist. Since the wheel
# is now the only run path, the scene lives under
# python/isaacteleop_examples/mujoco_xr/assets/ and ships as package data, which
# resolves identically in the wheel and in the source tree (the in-tree ctest
# path).
#
# Namespacing the package pushed BOTH the source tree and site-packages one
# directory deeper, together, so this is still one `.parent`. It stays one only
# as long as assets/ stays inside the mujoco_xr package -- hoisting it up to the
# namespace directory would need two, and the namespace has no owner to put
# files in.
#
# Plain __file__ arithmetic rather than importlib.resources: this package is
# always installed as real files on disk (it contains a compiled extension, so
# it can never be imported from a zip), and a Path is what --scene-xml and
# MjModel.from_xml_path want anyway.
#
# STILL POINTS AT tabletop.xml, which is still the default scene, and that is a
# deliberate constraint rather than inertia: tabletop.xml is the only scene that
# needs no fetch, so an unfetched checkout runs and tests unchanged. The scene
# CATALOGUE lives in robot_spec.SCENES; this is the one row of it that app.py
# names directly.
DEFAULT_SCENE = robot_spec.scene_path(
    robot_spec.scene_by_id(robot_spec.DEFAULT_SCENE_ID)
)

# Controller marker appearance. Half-extents in metres; translucent so the
# robot behind stays legible.
_MARKER_HALF_EXTENT = (0.02, 0.02, 0.02)
_MARKER_RGBA = {
    ControllersSource.LEFT: (0.20, 0.55, 1.00, 0.65),
    ControllersSource.RIGHT: (1.00, 0.45, 0.15, 0.65),
}

# WHICH HAND DRIVES THE ARM. One hand, one arm, and no flag: both shipped scenes
# contain exactly one arm, so a second controller has nothing to drive. The
# other hand is still TRACKED and still drawn as a marker -- that is what makes
# "the markers move but the arm does not" a readable symptom rather than an
# ambiguous one.
CONTROL_HAND = ControllersSource.RIGHT

# The target-pose box: where the clutch says the tool should be, as opposed to
# where the arm has got to. Green when engaged, grey when idle. It is the only
# visual indication of clutch state, and the gap between it and the tool is the
# IK's tracking error made visible.
_TARGET_HALF_EXTENT = (0.02, 0.02, 0.02)
_TARGET_RGBA_ENGAGED = (0.20, 1.00, 0.30, 0.50)
_TARGET_RGBA_IDLE = (0.70, 0.70, 0.70, 0.35)


def _clamp_dt(dt: float) -> float:
    """NaN-safe clamp into [0, MAX_DT_S].

    Spelled exactly like this, and NOT as ``min(max(dt, 0), MAX_DT_S)``:
    ``max(nan, 0)`` returns nan and ``min(nan, 0.1)`` returns nan, so the
    "obvious" form passes NaN straight through both limits and into mj_step.
    The comparison form sends NaN to 0 because ``nan > 0`` is False.
    """
    if dt > 0:
        return MAX_DT_S if dt > MAX_DT_S else dt
    return 0.0


class _HeadTravelProbe:
    """Separates "the scene is in the wrong place" from "the head is not tracked".

    Those two present IDENTICALLY through a headset and have disjoint fixes, so
    guessing between them costs a session each time. A scene that keeps a fixed
    offset from the operator -- rotating correctly, translating with them -- is
    not a calibration error and no constant in ``cpp/frames.hpp`` can correct
    it: it is what rendering against a view pose whose POSITION never changes
    looks like. Rotation-only (3DoF) tracking is the usual cause, and a
    streaming runtime can assert ``XR_VIEW_STATE_POSITION_VALID_BIT`` while
    still returning a pinned position, so the validity flags viz already checks
    (``openxr_session.cpp:554``) do not catch it.

    MEASURED FROM ``FrameInfo.views``, not from ``head_pose_now()``, for two
    reasons: those poses are exactly what ``renderer.render()`` consumes, so a
    pinned reading here IS the explanation for what the operator sees rather
    than a correlate of it; and ``head_pose_now()`` returns None without the
    time-conversion extension, which would make the diagnostic quietly absent
    on the runtimes most likely to need it.

    Reports peak displacement from the first sample, because an operator asked
    to "walk around" produces a maximum that is stable to read, where an
    instantaneous position is three numbers that mean nothing on their own.
    """

    # Long enough not to spam a 72 Hz loop, short enough that an operator who
    # takes one step sees the number move while they are still moving.
    _LOG_PERIOD_S = 2.0
    # Above headset jitter (millimetres) and below any deliberate motion.
    _MOVED_EPSILON_M = 0.05

    def __init__(self) -> None:
        self._origin: tuple[float, float, float] | None = None
        self._max_travel_m = 0.0
        self._next_log_s = 0.0
        self._called_it = False

    def sample(
        self, poses_xyz_qwxyz: list[float], view_count: int, now_s: float
    ) -> None:
        """One rendered frame's flattened view poses; call after _flatten_xr_views."""
        if view_count <= 0 or len(poses_xyz_qwxyz) < view_count * 7:
            return
        # Midpoint of the eyes = head position in the reference space. Averaged
        # rather than eye 0 so a head ROLL, which swings either eye on its own,
        # does not read as translation and mask a pinned position.
        center = tuple(
            sum(poses_xyz_qwxyz[v * 7 + axis] for v in range(view_count)) / view_count
            for axis in range(3)
        )
        if self._origin is None:
            self._origin = center
            self._next_log_s = now_s + self._LOG_PERIOD_S
            LOG.info(
                "head tracking: origin sample at (%.3f, %.3f, %.3f) m in the reference space. "
                "Walk or lean; the travel below must grow.",
                *center,
            )
            return

        travel = math.dist(center, self._origin)
        self._max_travel_m = max(self._max_travel_m, travel)
        if now_s < self._next_log_s:
            return
        self._next_log_s = now_s + self._LOG_PERIOD_S

        if self._max_travel_m >= self._MOVED_EPSILON_M:
            if not self._called_it:
                LOG.info(
                    "head tracking: 6DoF confirmed -- head has moved %.3f m from the origin sample. "
                    "A scene in the wrong PLACE from here is a calibration question, not a tracking one.",
                    self._max_travel_m,
                )
                self._called_it = True
            return

        LOG.warning(
            "head tracking: head has moved at most %.3f m since the origin sample. If you have been "
            "moving, the runtime is streaming ROTATION ONLY (3DoF) -- the view pose this app renders "
            "against has a pinned position, so the whole scene keeps a fixed offset from your head and "
            "no reference space or frames.py constant can anchor it. That is a CloudXR client/runtime "
            "question (device profile, 6DoF pose upload), not an app one.",
            self._max_travel_m,
        )


def _clock_stall_streak(streak: int, elapsed: float, should_render: bool) -> int:
    """Consecutive frames the runtime asked us to RENDER whose clock gave no time.

    Ported from ``MuJoCoXR/src/sim_scene.cc:102-111`` -- *"A stalled clock
    renders perfectly and steps nothing, with nothing in the log to say so."*

    ``should_render`` IS THE GATE, and without it this watchdog would be worse
    than nothing. ``viz_session.cpp:238`` does not call the backend at all
    while the session is below kRunning, so every session opens with a run of
    frames carrying ``should_render == False`` and ``predicted_display_time ==
    0`` -- and since no ``xrWaitFrame`` throttles them, this loop spins through
    hundreds in milliseconds while the operator is still putting the headset
    on. Counting those would fire an error at every single startup, and the
    first thing anyone does with a watchdog that cries wolf is delete it. A
    frame the runtime WANTS rendered but that carries no time is anomalous in
    every mode, which is what makes it worth reporting.

    Frames that are not rendered neither count nor reset the streak: they are
    not evidence either way. **A session that never reaches kRunning therefore
    stays silent, deliberately** -- it renders nothing either, so it is not the
    "perfect render, frozen physics" pathology this watchdog exists to name,
    and a headset showing nothing at all is a symptom the operator cannot miss.

    All three stalls reach here, because each leaves ``elapsed`` at 0:
    ``predicted_display_time`` stuck at 0 (``_frame_clock`` returns None, so
    ``previous_clock`` is never even set), stuck at a nonzero constant, and NaN
    (``_clamp_dt`` sends it to 0).
    """
    if not should_render:
        return streak
    return 0 if elapsed > 0.0 else streak + 1


def _build_pipeline() -> OutputCombiner:
    """Controllers only -- the sole device this example reads."""
    controllers = ControllersSource(name="controllers")
    return OutputCombiner(
        {
            ControllersSource.LEFT: controllers.output(ControllersSource.LEFT),
            ControllersSource.RIGHT: controllers.output(ControllersSource.RIGHT),
        }
    )


def _flatten_xr_views(info) -> tuple[list[float], list[float]]:
    """FrameInfo.views -> the flat float arrays the renderer takes.

    Filled field by field. viz.Pose3D.orientation is (w, x, y, z); a
    controller's GRIP_ORIENTATION is (x, y, z, w). Slice-assigning a 7-vector
    from one into the other is the classic way to get a silently wrong scene,
    so nothing here is ever sliced.
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
    """Per-frame, not init-time: the projection is rebuilt from per-frame fov.

    Transcribed from viz's own ``fov_to_projection_matrix``
    (src/viz/session/cpp/xr_backend.cpp), including its DELIBERATE angleUp -> bottom
    swap. `p` is column-major, so ``p[c * 4 + r]`` is ``P[c][r]``.
    """
    p00, p11, p23 = p[0], p[5], p[11]
    assert p00 > 0.0, (
        f"P[0][0]={p00}: left/right swapped, or a zeroed Fov reached the projection"
    )
    # THE load-bearing one. b = n*tan(angleUp) > 0 and t = n*tan(angleDown) < 0
    # give 2n/(t-b) < 0. That negative is the Y flip, and it is what drives
    # triangle winding -- a depth-range check touches only P[2][2] / P[2][3] /
    # P[3][2] and would not notice it going positive.
    assert p11 < 0.0, (
        f"P[1][1]={p11}: the angleUp->bottom Y flip is gone; winding will invert"
    )
    assert abs(p23 + 1.0) < 1e-6, f"P[2][3]={p23}: not a standard perspective divide"

    # Depth encoding, asserted as the contract we ship (near -> 0, far -> 1)
    # rather than as somebody else's formula, so it survives a viz refactor.
    # Two viz doc comments claim reverse-Z; the code is standard Z, and this is
    # the assertion that catches anyone who believes the comments.
    for z_view, expected in ((-near, 0.0), (-far, 1.0)):
        clip_z = p[10] * z_view + p[14]
        clip_w = p[11] * z_view + p[15]
        assert abs(clip_z / clip_w - expected) < 1e-4, (
            f"depth encoding broken: z_view={z_view} maps to {clip_z / clip_w}, expected {expected}"
        )


def _log_startup(resolution, scene: Path) -> None:
    """One block naming every assumption that is invisible at runtime."""
    try:
        version = importlib.metadata.version("isaacteleop")
    except importlib.metadata.PackageNotFoundError:
        version = "<not installed as a distribution>"
    trans = _mujoco_xr.TRANS_MJ_FROM_XR

    LOG.info("scene:      %s", scene)
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
        "reference space: LOCAL_FLOOR -- origin on the floor below the operator's start pose, so the z below is a "
        "measured floor datum. viz logs what the runtime actually offered on its own line."
    )
    LOG.info(
        "frames:     mj_from_xr translation = (%.3f, %.3f, %.3f) m. x is operator standoff; z is the FLOOR datum, "
        "valid because the reference space above is floor-origin. Neither term may be zeroed.",
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


def _draw_controller_markers(renderer, result) -> int:
    """Append one marker per validly-tracked controller. Returns how many.

    EXPECT THE MARKER TO TRAIL THE HAND, and do not read that as a frames bug.
    The scene is rendered for ``predicted_display_time`` -- a time in the
    FUTURE -- while ``teleop.step()`` samples the grip pose at now, so the
    marker is drawn where the hand WAS, by roughly one prediction interval
    (order 10-30 ms). It is a uniform lag along the direction of motion, not a
    wrong axis, a swapped sign or a rotated frame. Since this marker is the
    only frames-convention validation artifact in the app, that distinction is
    the whole point. Fixing it means pose extrapolation, which is out of scope
    here.

    THE GATE IS NOT OPTIONAL. When a controller is untracked, the underlying
    grip_pose is left DEFAULT-CONSTRUCTED at position (0, 0, 0), and in MuJoCo
    world (0, 0, 0) is the workspace datum -- the table origin. An ungated read
    therefore draws a marker exactly where a legitimate pose could be, which is
    indistinguishable from real data. Read nothing unless both checks pass.
    """
    drawn = 0
    for name in (ControllersSource.LEFT, ControllersSource.RIGHT):
        controller = result[name]
        if controller.is_none:
            continue
        if not bool(controller[ControllerInputIndex.GRIP_IS_VALID]):
            continue
        position = controller[ControllerInputIndex.GRIP_POSITION]
        orientation = controller[ControllerInputIndex.GRIP_ORIENTATION]
        # Field by field, and named for the order they are in. GRIP_ORIENTATION
        # is xyzw; mj_from_xr_quat is the one and only place that reorders.
        p_xr = [float(position[0]), float(position[1]), float(position[2])]
        q_xyzw = [
            float(orientation[0]),
            float(orientation[1]),
            float(orientation[2]),
            float(orientation[3]),
        ]
        renderer.add_marker(
            pos_mj=_mujoco_xr.mj_from_xr_pos(p_xr),
            quat_mj_wxyz=_mujoco_xr.mj_from_xr_quat(q_xyzw),
            half_extent=list(_MARKER_HALF_EXTENT),
            rgba=list(_MARKER_RGBA[name]),
        )
        drawn += 1
    return drawn


def _draw_target_marker(renderer, control) -> None:
    """The clutch target, drawn last so it lands over the arm."""
    renderer.add_marker(
        pos_mj=[float(v) for v in control.target_pos],
        quat_mj_wxyz=[float(v) for v in control.target_quat],
        half_extent=list(_TARGET_HALF_EXTENT),
        rgba=list(_TARGET_RGBA_ENGAGED if control.engaged else _TARGET_RGBA_IDLE),
    )


def _build_control(model, data):
    """A ``teleop.Teleop`` for this model, or None with the reason logged.

    ALWAYS LOGGED, AND AT WARNING. A scene with no robot in it (``tabletop``) is
    a legitimate configuration and reaches here too, so this is not an error --
    but a scene that HAS a robot and failed to resolve produces the identical
    outcome: a robot that draws perfectly and never moves, which on a headset is
    indistinguishable from a dead controller. This string is the only thing that
    tells the two apart, so it is never swallowed.
    """
    try:
        return teleop.Teleop(model, data)
    except ValueError as exc:
        LOG.warning("teleop control is OFF: %s", exc)
        return None


def _frame_clock(info) -> float | None:
    """The single simulation clock, or None if this frame carries no time.

    ``predicted_display_time`` -- the time the frame will actually be
    DISPLAYED, which is what the geometry should correspond to.
    ``FrameInfo.delta_time`` is CPU wall-clock and appears nowhere in this app.

    RETURNS None WHEN ``predicted_display_time`` IS 0, and that case is not
    hypothetical. ``src/viz/session/cpp/viz_session.cpp:255-256`` sets
    ``should_render = false`` **and** ``predicted_display_time = 0`` together on
    every frame the runtime does not want rendered -- which is every frame
    before the session reaches kRunning, i.e. the start of every single
    session. The value is ZEROED, not stale, so sampling it would record
    ``previous_clock = 0`` and make the next real frame compute
    ``dt = t_now - 0``: clamped to MAX_DT_S and then stepped 0.1 s / timestep
    (50 mj_steps at the default 2 ms) inside one display frame. That is a
    visible lurch, at every startup.

    The caller must skip the SAMPLE and leave the accumulator alone: the
    simulation still owes the time between the last two real samples.
    """
    if info.predicted_display_time == 0:
        return None
    return info.predicted_display_time / 1e9


def _resolve_scene(args: argparse.Namespace) -> Path:
    """--scene-xml if given, else the --scene catalogue row. Never both.

    The catalogue row is checked for its FETCHED half before MuJoCo sees the
    path, because MjModel.from_xml_path's own failure for a missing
    ``<include>`` target is a bare "Error opening file <mesh>.stl" naming a file
    nobody asked for. robot_spec.scene_missing() names the fetch script instead.

    --scene-xml deliberately does NOT get that check: it is the escape hatch for
    a scene this catalogue does not know about, so there is nothing to check it
    against, and MuJoCo's own error is the right one there.
    """
    if args.scene_xml is not None:
        return Path(args.scene_xml).resolve()
    scene = robot_spec.scene_by_id(args.scene)
    missing = robot_spec.scene_missing(scene)
    if missing is not None:
        raise SystemExit(f"mujoco_xr: {missing}")
    return robot_spec.scene_path(scene)


def run(args: argparse.Namespace, scene_path: Path) -> int:
    model = mujoco.MjModel.from_xml_path(str(scene_path))
    data = mujoco.MjData(model)

    # ORDER IS LOAD-BEARING: build the pipeline, aggregate the OpenXR
    # extensions its trackers need, put them on the VizSessionConfig, and ONLY
    # THEN create the session. VizSession is what calls xrCreateInstance, so an
    # extension discovered later cannot be added -- and a controller tracker
    # without XR_NVX1_action_context is silently dead rather than an error.
    pipeline = _build_pipeline()
    required_extensions = get_required_oxr_extensions_from_pipeline(pipeline)

    config = viz.VizSessionConfig()
    config.mode = _DISPLAY_MODE
    config.app_name = "MuJoCoXR"
    config.xr_near_z = NEAR_Z
    config.xr_far_z = FAR_Z
    config.required_extensions = required_extensions
    # THE FLOOR DATUM, AND THE REASON kTransMjFromXr's z means anything. This
    # app draws world-locked geometry at a height above the FLOOR -- the table
    # top is MuJoCo z=0, which cpp/frames.hpp puts 0.73 m up -- so the session
    # origin has to be on the floor for that number to be a measurement rather
    # than a guess about where the operator was standing. kLocal, the viz
    # default, puts the origin at the headset's start pose: the table then
    # renders 0.73 m above the operator's HEAD, which is what this used to do.
    # kLocalFloor keeps kLocal's position and facing (so the -1.0 m standoff is
    # unaffected) and moves y=0 down to the floor. It is core in OpenXR 1.1;
    # a runtime that cannot supply it throws here naming the space, which is
    # deliberate -- see the note in viz_session.hpp.
    config.xr_reference_space = viz.XrReferenceSpace.kLocalFloor
    # Alpha 0 = "show passthrough here", and this is set UNCONDITIONALLY while
    # the runtime is what decides whether that alpha is honoured: viz only sets
    # XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT when the environment
    # blend mode is non-opaque (src/viz/session/cpp/xr_backend.cpp:1210). On an
    # opaque VR headset the flag is 0, destination alpha is discarded, and the
    # background composites BLACK rather than passthrough. That is accepted:
    # this example targets an AR/passthrough headset, and a black surround on a
    # VR one is legible rather than broken. Making it conditional needs
    # environment_blend_mode() exposed to Python, which it is not.
    config.clear_color = (0.0, 0.0, 0.0, 0.0)

    session = viz.VizSession.create(config)
    renderer = None
    try:
        resolution = session.get_recommended_resolution()

        layer_config = viz.ProjectionLayerConfig()
        layer_config.name = "mujoco_scene"
        layer_config.view_resolution = resolution
        layer_config.color_format = viz.PixelFormat.kRGBA8
        layer_config.depth_format = viz.PixelFormat.kD32F
        layer_config.stereo = _VIEW_COUNT == 2
        layer = session.add_projection_layer(layer_config)

        renderer = _mujoco_xr.Renderer(
            vk_physical_device=session.vk_physical_device,
            vk_device=session.vk_device,
            vk_queue_family_index=session.vk_queue_family_index,
            width=resolution.width,
            height=resolution.height,
            view_count=_VIEW_COUNT,
            near_z=NEAR_Z,
            far_z=FAR_Z,
            model_address=model._address,
        )

        _log_startup(resolution, scene_path)

        # Built AFTER the startup block so the robot line it logs reads as part
        # of the same report, and BEFORE the frame loop so a resolution failure
        # is visible at startup rather than discovered by an arm that never
        # moves. None for a scene with no arm in it.
        control = _build_control(model, data)
        if control is not None:
            # START AT `home`, and this is not cosmetic. A fresh MjData is at
            # `qpos0` -- all zeros for both shipped arms -- which is NOT the
            # posture either scene authors. Measured on the SO-101: without this
            # the session opens with the arm folded at zero, the clutch target
            # latched onto the zero-pose TCP at (0.012, -0.000, -0.098) (below
            # the table, at the base), and `ctrl` all zeros, which by the jaw
            # table is a 16.3 mm aperture -- nearly closed -- rather than the
            # 1.745 / 129.9 mm the `home` keyframe authors. The operator would
            # then have to press A before anything looked right.
            #
            # AFTER _build_control, deliberately: Teleop.__init__ latches its
            # target from `data`, and Teleop.reset re-latches it after running
            # mj_forward. Doing it inside __init__ instead would change the
            # constructor's contract, which the tests rely on.
            control.reset(model, data)

        oxr = session.get_oxr_handles()
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
            _loop(session, layer, renderer, model, data, teleop_session, control)
    finally:
        # The renderer borrows the session's device: it must go first.
        if renderer is not None:
            renderer.close()
        session.destroy()
    return 0


def _loop(session, layer, renderer, model, data, teleop_session, control) -> None:
    view_count = renderer.view_count
    # One source, for one hand. Constructed here rather than per frame so it is
    # obvious there is exactly one.
    source = teleop.XrControllerSource(CONTROL_HAND)
    previous_clock: float | None = None
    # Fixed-step accumulator. NOT reset or drained on a non-render frame: the
    # simulation owes that time regardless of whether anything was displayed.
    accumulator = 0.0
    checked_projection = False
    markers_logged = -1
    stalled = 0
    head_probe = _HeadTravelProbe()

    while not session.should_close():
        info = session.begin_frame()
        try:
            # None means "this frame carries no usable timestamp" -- skip the
            # sample entirely rather than recording a zero. See _frame_clock.
            now = _frame_clock(info)
            elapsed = 0.0
            if now is not None:
                if previous_clock is not None:
                    elapsed = _clamp_dt(now - previous_clock)
                    accumulator += elapsed
                previous_clock = now

            # Say so once when the clock has died, instead of rendering a
            # perfect, frozen scene in silence. Fires on == rather than >= so a
            # stall reports once per episode, not once per frame.
            stalled = _clock_stall_streak(stalled, elapsed, info.should_render)
            if stalled == STALL_FRAMES:
                LOG.error(
                    "clock stalled: %s has not advanced across %d rendered frames; physics is frozen "
                    "while rendering continues normally.",
                    _CLOCK_NAME,
                    STALL_FRAMES,
                )

            # ── CONTROL, BEFORE THE PHYSICS IT COMMANDS ──────────────────
            # Above the `should_render` gate and above the step loop, and both
            # of those placements are the point. Sampling below the gate was
            # harmless while the poses were only markers; once they drive
            # `d.ctrl` it means the simulation advances open-loop on every
            # non-rendered frame, holding the last command while the operator's
            # hand keeps moving.
            #
            # `elapsed` is what reaches the rate limiter, and it has already
            # been through _clamp_dt -- so a NaN clock arrives as 0, which stops
            # the target rather than switching the limit off.
            #
            # GATED, and the gate is the exact statement of the requirement
            # rather than "every frame": sample when this frame will STEP
            # PHYSICS (so control precedes anything it commands) or will BE
            # DRAWN (so the markers are not a frame stale). An ungated version
            # calls teleop_session.step(), and therefore xrSyncActions, on the
            # pre-kRunning startup burst -- viz_session.cpp:238 does not call the
            # backend below kRunning and nothing throttles those frames, so this
            # loop spins through hundreds of them in milliseconds while the
            # operator is still putting the headset on. Those frames carry no
            # time and render nothing, so there is nothing for control to do on
            # them, and syncing actions at kilohertz is not something this app
            # should be the first to try on a runtime.
            result = None
            will_step = accumulator >= model.opt.timestep
            if will_step or info.should_render:
                result = teleop_session.step()
                if control is not None:
                    control.update(model, data, source.sample(result), elapsed)

            steps = 0
            while accumulator >= model.opt.timestep and steps < 64:
                mujoco.mj_step(model, data)
                accumulator -= model.opt.timestep
                steps += 1

            if not info.should_render:
                # Skip the draw. Deliberately do NOT touch the accumulator.
                continue

            renderer.update_scene(model._address, data._address)
            renderer.clear_markers()
            if result is not None:
                drawn = _draw_controller_markers(renderer, result)
                if drawn != markers_logged:
                    LOG.info("controller markers: %d validly tracked", drawn)
                    markers_logged = drawn
            if control is not None:
                _draw_target_marker(renderer, control)
            # NOT redundant with add_marker()'s own full-scene throw, because
            # add_marker only runs when there is something to draw -- a scene
            # with no arm and no validly-tracked controller reaches neither
            # branch above. This is the one check that covers mjv_updateScene
            # alone filling mjvScene. Measured against mujoco 3.11.0: that case
            # prints "WARNING: Pre-allocated visual geom buffer is full" on
            # stderr, truncates, and returns normally with ngeom == maxgeom. A
            # warning line in a frame loop is not something anyone sees, so a
            # --scene with too much in it would otherwise render with parts
            # missing and no error anywhere.
            if renderer.ngeom >= renderer.maxgeom:
                raise RuntimeError(
                    f"mjvScene is full: ngeom={renderer.ngeom} maxgeom={renderer.maxgeom}. "
                    "Geometry is being dropped -- use a smaller scene, or raise kMaxGeom "
                    "in cpp/scene_renderer.cpp."
                )

            # A view-count mismatch is rejected by render() below, which sees
            # the flattened lengths and says so in those terms. There is
            # deliberately no second check here.
            poses, fovs = _flatten_xr_views(info)
            head_probe.sample(poses, view_count, time.monotonic())

            renderer.render(poses, fovs)

            for view in range(view_count):
                _assert_projection(renderer.projection(view), NEAR_Z, FAR_Z)
            if not checked_projection:
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
            session.end_frame()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # A CATALOGUE ID, not a path -- and there is deliberately no --robot flag to
    # go with it. The robot is always PROBED from the loaded model, so a caller
    # cannot assert a robot the model is not. `--scene-xml` below is the escape
    # hatch for a scene this catalogue does not list.
    parser.add_argument(
        "--scene",
        choices=robot_spec.scene_ids(),
        default=robot_spec.DEFAULT_SCENE_ID,
        help=(
            "Scene to load: "
            + "; ".join(f"{s.id} = {s.label}" for s in robot_spec.SCENES)
            + ". Everything but the default needs "
            + robot_spec.FETCH_SCRIPT
            + " to have been run (and the wheel reinstalled after it)."
        ),
    )
    parser.add_argument(
        "--scene-xml",
        default=None,
        help=(
            "Escape hatch: load this MuJoCo scene XML instead of a --scene "
            "catalogue id. Its table TOP must sit at z=0 -- compare the shipped "
            "scenes, which are package data beside this module (see the path on "
            "the 'scene:' line of the startup log)."
        ),
    )
    parser.add_argument("--verbose", action="store_true", help="Debug-level logging.")
    CloudXRLauncher.add_launcher_arguments(parser)
    args = parser.parse_args(argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[mujoco_xr] %(message)s",
    )

    # BEFORE launch_context, and that ordering is the whole point of doing it
    # here rather than inside run(). CloudXRLauncher.launch_context STARTS A
    # RUNTIME PROCESS on entry and tears it down on exit, so a --scene whose
    # assets have not been fetched -- an ordinary, expected mistake on a fresh
    # clone -- would otherwise spin the runtime up and back down before printing
    # a one-line "run the fetch script" message, and the message lands buried in
    # the middle of the runtime's own startup and shutdown logging. Everything
    # cheap and local happens first; nothing here touches a device.
    scene_path = _resolve_scene(args)

    with CloudXRLauncher.launch_context(args) as launcher:
        if launcher is not None:
            LOG.info("CloudXR runtime started (WSS log: %s)", launcher.wss_log_path)
        try:
            return run(args, scene_path)
        except KeyboardInterrupt:
            LOG.info("interrupted")
            return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
