# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MuJoCo scene rendered into a Televiz XR session, with controller markers.

Single process, single thread, one OpenXR session:

    VizSession(kXr)  ──get_oxr_handles()──▶  TeleopSession
         │                                        │
         │ vk_device / vk_physical_device         │ controller grip poses
         ▼                                        ▼
    _mujoco_xr.Renderer  ──__cuda_array_interface__──▶  ProjectionLayer.submit()

SCOPE: the controller poses are drawn as MARKERS ONLY. There is no IK, no
clutch, no rate limiting and no jaw mapping here, deliberately -- a
frame-convention bug and a control bug produce the identical symptom ("the arm
jumped"), and separating them is what makes the first one debuggable.
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

from . import _mujoco_xr

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

# --mode. Three values, and each one is reachable somewhere different:
#   xr        the product path; needs a headset and a CloudXR runtime.
#   window    a desktop window; needs a working present-capable surface.
#   offscreen renders into memory and submits, with NO window system, no
#             headset and no runtime. It is the only mode that runs this app's
#             own frame loop on a headless machine, which is what makes the
#             startup log and the per-frame projection assertion observable
#             without hardware.
# The app branches on the CONFIGURED mode and never on the fov it got back --
# see _debug_view for why that distinction is load-bearing.
_MODES = {
    "xr": viz.DisplayMode.kXr,
    "window": viz.DisplayMode.kWindow,
    "offscreen": viz.DisplayMode.kOffscreen,
}

# PACKAGE DATA, resolved from inside the package -- one `.parent`, not three.
#
# It used to walk three parents up to examples/mujoco_xr/assets/, which was
# correct only in the old install tree. From site-packages/mujoco_xr/app.py that
# same walk points at site-packages/../.. -- outside site-packages entirely, at a
# path that does not exist. Since the wheel is now the only run path, the scene
# lives under python/mujoco_xr/assets/ and ships as package data, which resolves
# identically in the wheel and in the source tree (the in-tree ctest path).
#
# Plain __file__ arithmetic rather than importlib.resources: this package is
# always installed as real files on disk (it contains a compiled extension, so
# it can never be imported from a zip), and a Path is what --scene and
# MjModel.from_xml_path want anyway.
DEFAULT_SCENE = Path(__file__).resolve().parent / "assets" / "tabletop.xml"

# Controller marker appearance. Half-extents in metres; translucent so the
# robot behind stays legible.
_MARKER_HALF_EXTENT = (0.02, 0.02, 0.02)
_MARKER_RGBA = {
    ControllersSource.LEFT: (0.20, 0.55, 1.00, 0.65),
    ControllersSource.RIGHT: (1.00, 0.45, 0.15, 0.65),
}


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


def _debug_view(resolution) -> tuple[list[float], list[float]]:
    """An EXPLICIT camera pose + symmetric fov for the non-XR modes.

    Two separate traps live here, and neither is hypothetical:

    1. ``window_backend.cpp`` (and ``offscreen_backend.cpp``) fill
       ``FrameInfo.views`` with a single default-constructed ``ViewInfo``, whose
       ``Fov`` is four ZEROS. Feeding that to the projection gives
       ``right - left == 0`` -> ``P[0][0] = +inf`` and
       ``P[2][0] = P[2][1] = NaN``. So the app branches on the CONFIGURED mode,
       never on inspecting the fov it got back.
    2. That same default ``ViewInfo`` has an IDENTITY pose, which puts the eye
       at the XR origin. Under this app's frames convention the XR origin is
       on the floor, so the camera would be inside the table looking at
       nothing.
    """
    aspect = resolution.width / resolution.height
    half_v = math.radians(30.0)
    half_h = math.atan(math.tan(half_v) * aspect)
    fov = [-half_h, half_h, half_v, -half_v]

    # Eye at operator height, a little behind the workspace, pitched down 25
    # degrees. XR space is Y-up with -Z forward; pitching the view down is a
    # NEGATIVE rotation about +X.
    pitch = math.radians(-25.0)
    pose = [
        0.0,
        1.60,
        0.30,
        math.cos(pitch / 2.0),  # qw
        math.sin(pitch / 2.0),  # qx
        0.0,
        0.0,
    ]
    return pose, fov


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


def _log_startup(mode, resolution, clock_source: str, scene: Path) -> None:
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
        "mode:       %s   view resolution: %sx%s",
        mode,
        resolution.width,
        resolution.height,
    )
    LOG.info(
        "clip:       near=%.4f far=%.2f (one pair -> VizSessionConfig, projection, submitted depth)",
        NEAR_Z,
        FAR_Z,
    )
    LOG.info(
        "reference space: LOCAL. VizSession exposes no reference-space option and its backend never sets one, "
        "so the origin is wherever the headset was at session start -- NOT the floor."
    )
    LOG.info(
        "frames:     mj_from_xr translation = (%.3f, %.3f, %.3f) m. x is operator standoff; z is a FLOOR datum "
        "and is only correct if the reference-space origin is on the floor (see above). Neither term may be zeroed.",
        trans[0],
        trans[1],
        trans[2],
    )
    LOG.info("clock:      %s", clock_source)
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


def _frame_clock(info, mode) -> float | None:
    """The single simulation clock, or None if this frame carries no time.

    In kXr this is ``predicted_display_time`` -- the time the frame will
    actually be DISPLAYED, which is what the geometry should correspond to.
    ``FrameInfo.delta_time`` is CPU wall-clock and appears nowhere in this app.

    RETURNS None IN kXr WHEN ``predicted_display_time`` IS 0, and that case is
    not hypothetical. ``src/viz/session/cpp/viz_session.cpp:255-256`` sets
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

    ``predicted_display_time`` is 0 in kWindow / kOffscreen as well, so those
    modes use ``time.monotonic()`` instead -- there is no runtime to predict
    for. Which clock is live is printed at startup.
    """
    if mode == viz.DisplayMode.kXr:
        if info.predicted_display_time == 0:
            return None
        return info.predicted_display_time / 1e9
    return time.monotonic()


def run(args: argparse.Namespace) -> int:
    mode = _MODES[args.mode]
    scene_path = Path(args.scene).resolve()

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
    config.mode = mode
    config.app_name = "MuJoCoXR"
    config.xr_near_z = NEAR_Z
    config.xr_far_z = FAR_Z
    config.required_extensions = required_extensions
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
        view_count = 2 if mode == viz.DisplayMode.kXr else 1

        layer_config = viz.ProjectionLayerConfig()
        layer_config.name = "mujoco_scene"
        layer_config.view_resolution = resolution
        layer_config.color_format = viz.PixelFormat.kRGBA8
        layer_config.depth_format = viz.PixelFormat.kD32F
        layer_config.stereo = view_count == 2
        layer = session.add_projection_layer(layer_config)

        renderer = _mujoco_xr.Renderer(
            vk_physical_device=session.vk_physical_device,
            vk_device=session.vk_device,
            vk_queue_family_index=session.vk_queue_family_index,
            width=resolution.width,
            height=resolution.height,
            view_count=view_count,
            near_z=NEAR_Z,
            far_z=FAR_Z,
            model_address=model._address,
        )

        # One conditional, two spellings of the same fact: the short name is
        # what the stall watchdog names in an error line, the long one is what
        # the startup block prints. Derived together so they cannot drift.
        clock_name, clock_source = (
            (
                "FrameInfo.predicted_display_time",
                "FrameInfo.predicted_display_time (XR); frames with no prediction are skipped, not sampled as 0",
            )
            if mode == viz.DisplayMode.kXr
            else (
                "time.monotonic()",
                "time.monotonic() (predicted_display_time is 0 outside kXr)",
            )
        )
        _log_startup(mode, resolution, clock_source, scene_path)

        if mode == viz.DisplayMode.kXr:
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
            with TeleopSession(teleop_config) as teleop:
                _loop(
                    session,
                    layer,
                    renderer,
                    model,
                    data,
                    mode,
                    resolution,
                    teleop,
                    clock_name,
                )
        else:
            LOG.info(
                "control disengaged: %s has no OpenXR session, so no controllers and no markers.",
                mode,
            )
            _loop(
                session,
                layer,
                renderer,
                model,
                data,
                mode,
                resolution,
                teleop=None,
                clock_name=clock_name,
            )
    finally:
        # The renderer borrows the session's device: it must go first.
        if renderer is not None:
            renderer.close()
        session.destroy()
    return 0


def _loop(
    session, layer, renderer, model, data, mode, resolution, teleop, clock_name
) -> None:
    view_count = renderer.view_count
    # `resolution` is passed in rather than re-queried: run() already asked for
    # it and sized both the layer and the renderer from that answer, so a second
    # call here would be a second chance for the three to disagree.
    debug_pose, debug_fov = _debug_view(resolution)
    previous_clock: float | None = None
    # Fixed-step accumulator. NOT reset or drained on a non-render frame: the
    # simulation owes that time regardless of whether anything was displayed.
    accumulator = 0.0
    checked_projection = False
    markers_logged = -1
    stalled = 0

    while not session.should_close():
        info = session.begin_frame()
        try:
            # None means "this frame carries no usable timestamp" -- skip the
            # sample entirely rather than recording a zero. See _frame_clock.
            now = _frame_clock(info, mode)
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
                    clock_name,
                    STALL_FRAMES,
                )

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
            if teleop is not None:
                result = teleop.step()
                drawn = _draw_controller_markers(renderer, result)
                if drawn != markers_logged:
                    LOG.info("controller markers: %d validly tracked", drawn)
                    markers_logged = drawn
            # NOT redundant with add_marker()'s own full-scene throw, because
            # add_marker only runs when `teleop is not None` -- the non-XR modes
            # never reach it. This is the one check that covers mjv_updateScene
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

            if mode == viz.DisplayMode.kXr:
                # A view-count mismatch is rejected by render() below, which
                # sees the flattened lengths and says so in those terms. There
                # is deliberately no second check here.
                poses, fovs = _flatten_xr_views(info)
            else:
                poses, fovs = list(debug_pose), list(debug_fov)

            renderer.render(poses, fovs)

            for view in range(view_count):
                _assert_projection(renderer.projection(view), NEAR_Z, FAR_Z)
            if not checked_projection:
                LOG.info(
                    "projection convention verified on the first rendered frame (P[1][1] < 0, near->0, far->1)"
                )
                checked_projection = True

            if view_count == 2:
                layer.submit(
                    renderer.color(0),
                    renderer.depth(0),
                    renderer.color(1),
                    renderer.depth(1),
                )
            else:
                layer.submit(renderer.color(0), renderer.depth(0))
        finally:
            # end_frame() follows EVERY begin_frame(), including the
            # should_render == False path and any exception above. Skipping it
            # wedges the frame loop.
            session.end_frame()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--scene",
        default=str(DEFAULT_SCENE),
        help=(
            "MuJoCo scene XML. Its table TOP must sit at z=0 -- compare the default, "
            "which ships as package data beside this module (see the path on the "
            "'scene:' line of the startup log)."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=tuple(_MODES),
        default="xr",
        help=(
            "xr: stereo through the headset, with controller markers. "
            "window: a single desktop view with an explicit debug camera and NO controllers; needs a "
            "present-capable surface and is known-failing on Tegra/Xvfb hosts. "
            "offscreen: the same single view rendered and submitted with no window system at all -- "
            "the mode that runs on a headless machine. Both non-xr modes run until interrupted."
        ),
    )
    parser.add_argument("--verbose", action="store_true", help="Debug-level logging.")
    CloudXRLauncher.add_launcher_arguments(parser)
    args = parser.parse_args(argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[mujoco_xr] %(message)s",
    )

    with CloudXRLauncher.launch_context(args) as launcher:
        if launcher is not None:
            LOG.info("CloudXR runtime started (WSS log: %s)", launcher.wss_log_path)
        try:
            return run(args)
        except KeyboardInterrupt:
            LOG.info("interrupted")
            return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
