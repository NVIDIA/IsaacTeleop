# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A MuJoCo scene drawn into a Televiz XR session.

One OpenXR session shared between VizSession (rendering) and TeleopSession
(input); the scene is drawn by MuJoCo's own renderer and reaches
ProjectionLayer.submit() by CUDA pointer, never through host memory.

    VizSession(kXr)  ──get_oxr_handles()──▶  TeleopSession
         │                                        │
         │ recommended resolution                 │ controller grip poses
         ▼                                        ▼                      │
    _mujoco_xr.Renderer  ──__cuda_array_interface__──▶  ProjectionLayer  │
         ▲                                                               │
         └──────────────── mjData.mocap_pos/_quat ◀─────────────────────┘

The renderer needs an OpenGL context current on this thread, made below and torn
down after it; viz and the renderer meet through CUDA alone, on VizSession's GPU.

C++ owns mjvScene/mjvOption/mjvCamera/mjrContext; Python owns
mjModel/mjData/mj_step, so everything reading a controller and writing mjData is
testable without a GPU. Frame order is load-bearing: input is sampled before the
physics it feeds, on every frame that will step or draw.
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
from isaacteleop.retargeting_engine.tensor_types import ControllerInputIndex
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

LOG = logging.getLogger("mujoco_xr")

# The app's only clip planes. VizSessionConfig, the projection and the submitted
# depth must all agree, or world-locked geometry swims under head motion -- and
# only a headset shows it. There is no near/far literal in cpp/, by construction.
NEAR_Z = 0.05
FAR_Z = 50.0

# Wall-clock ceiling for one simulation advance. See _clamp_dt.
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

# Package data, so it resolves the same from the wheel and the source tree. Keep
# it ABSOLUTE: on mujoco 3.11.0 a relative model path mis-composes the mesh paths
# of an <include>d fragment and fails naming a file that is right there on disk.
DEFAULT_SCENE = Path(__file__).parent / "assets" / "scene.xml"

# Checked by name before MuJoCo sees the scene: its failure for a missing
# <include> target is a bare "Error opening file <mesh>.stl", naming a file
# nobody asked for.
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


# One hand and no flag: the ghost is a right-handed gripper.
GHOST_HAND = ControllersSource.RIGHT

# The two mocap bodies leader_gripper.xml declares.
GHOST_BODY = "leader_ghost"
GHOST_JAW_BODY = "leader_ghost_jaw"

# ── Where the ghost sits on the hand ───────────────────────────────────────
# Measured on a headset, not derived: this is a claim about a hand holding a
# CONTROLLER, so do not re-derive it from the mesh. Euler degrees, intrinsic
# XYZ, i.e. MuJoCo's `euler=`. Re-tuning procedure and the mesh trap:
# README.md#where-the-ghost-sits-on-the-hand-apppy.
_EULER_GRIP_FROM_GHOST_DEG = (60, 180, 270)
_POS_GRIP_FROM_GHOST = np.array((0, 0.02, -0.025))

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

    Right-multiplication is what makes it intrinsic. Spelled out rather than
    calling mju_euler2Quat so the sequence is visible where it is used.
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

    Comparisons, not min/max: max(nan, 0) is nan, so the obvious form passes
    NaN through both limits and into mj_step.
    """
    if dt > 0:
        return MAX_DT_S if dt > MAX_DT_S else dt
    return 0.0


def _build_pipeline() -> OutputCombiner:
    """Controllers, plus the shipped SO-101 jaw retargeter as a graph edge.

    A BaseRetargeter node in the pipeline, not a library call beside it. With no
    robot in the scene the jaw it drives is the operator's own trigger.
    """
    controllers = ControllersSource(name="controllers")
    jaw = SO101GripperRetargeter(name="ghost_jaw", input_device=GHOST_HAND).connect(
        {GHOST_HAND: controllers.output(GHOST_HAND)}
    )
    return OutputCombiner(
        {
            ControllersSource.LEFT: controllers.output(ControllersSource.LEFT),
            ControllersSource.RIGHT: controllers.output(ControllersSource.RIGHT),
            GRIPPER_COMMAND_KEY: jaw.output(GRIPPER_COMMAND_KEY),
        }
    )


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


def _update_ghost(data, ghost: _GhostChannels, result) -> None:
    """Lock the leader gripper to the GHOST_HAND grip pose; swing its trigger.

    Keep the validity gate: an untracked controller reports (0, 0, 0), which is
    the scene origin and a place a legitimate pose could put it, so freezing is
    the honest rendering of "tracking lost" and there is no else branch.
    _QUAT_GRIP_FROM_GHOST right-multiplies because it is fixed in the gripper's
    frame; left-multiplying swings the ghost around the room as the operator turns.
    """
    controller = result[GHOST_HAND]
    if controller.is_none:
        return
    if not bool(controller[ControllerInputIndex.GRIP_IS_VALID]):
        return
    position = controller[ControllerInputIndex.GRIP_POSITION]
    orientation = controller[ControllerInputIndex.GRIP_ORIENTATION]
    p_xr = [float(position[0]), float(position[1]), float(position[2])]
    q_xyzw = [
        float(orientation[0]),
        float(orientation[1]),
        float(orientation[2]),
        float(orientation[3]),
    ]

    q_grip = np.array(_mujoco_xr.mj_from_xr_quat(q_xyzw), dtype=float)
    p_grip = np.array(_mujoco_xr.mj_from_xr_pos(p_xr), dtype=float)

    q_body = np.empty(4)
    mujoco.mju_mulQuat(q_body, q_grip, _QUAT_GRIP_FROM_GHOST)
    p_offset = np.empty(3)
    mujoco.mju_rotVecQuat(p_offset, _POS_GRIP_FROM_GHOST, q_grip)
    p_body = p_grip + p_offset

    data.mocap_pos[ghost.body] = p_body
    data.mocap_quat[ghost.body] = q_body

    # The deadzone and clamp are the retargeter's contract, not this app's.
    # Rotated ABOUT the hinge, not placed at it: the jaw's XML rest pose equals
    # the ghost's, so the pivot lives in exactly one place.
    closedness = float(result[GRIPPER_COMMAND_KEY][0])
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


def _frame_clock(info) -> float | None:
    """The simulation clock, or None if this frame carries no time.

    viz zeroes predicted_display_time with should_render on every frame before
    kRunning; sampling it makes the next real frame compute dt from 0 and step
    50 times in one display frame. The caller must skip it entirely.
    """
    if info.predicted_display_time == 0:
        return None
    return info.predicted_display_time / 1e9


def run() -> int:
    model = mujoco.MjModel.from_xml_path(str(DEFAULT_SCENE))
    data = mujoco.MjData(model)

    # Order is load-bearing: VizSession calls xrCreateInstance, so an extension
    # discovered after it cannot be added -- and a controller tracker missing
    # XR_NVX1_action_context is silently dead rather than an error.
    pipeline = _build_pipeline()
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
            _loop(viz_session, layer, renderer, model, data, teleop_session, ghost)
    finally:
        # Innermost first: the renderer's GL objects need a current context.
        if renderer is not None:
            renderer.close()
        if gl_context is not None:
            gl_context.free()
        viz_session.destroy()
    return 0


def _loop(viz_session, layer, renderer, model, data, teleop_session, ghost) -> None:
    view_count = renderer.view_count
    previous_clock: float | None = None
    # NOT reset or drained on a non-render frame: the simulation owes that time
    # whether or not anything was displayed.
    accumulator = 0.0
    checked_frustum = False

    while not viz_session.should_close():
        info = viz_session.begin_frame()
        try:
            # None means no usable timestamp -- skip the sample, never record 0.
            now = _frame_clock(info)
            if now is not None:
                if previous_clock is not None:
                    accumulator += _clamp_dt(now - previous_clock)
                previous_clock = now

            # Above both the should_render gate and the step loop, so it
            # precedes the physics it feeds. Gated rather than every frame: an
            # ungated step() calls xrSyncActions on the unthrottled
            # pre-kRunning burst, hundreds of frames in milliseconds.
            result = None
            will_step = accumulator >= model.opt.timestep
            if will_step or info.should_render:
                result = teleop_session.step()
                _update_ghost(data, ghost, result)

            steps = 0
            while accumulator >= model.opt.timestep and steps < 64:
                mujoco.mj_step(model, data)
                accumulator -= model.opt.timestep
                steps += 1

            if not info.should_render:
                # Deliberately does NOT touch the accumulator.
                continue

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
    # plainly instead of buried in the runtime's own startup logging.
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
