# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A MuJoCo scene drawn into a Televiz XR session.

One OpenXR session shared between VizSession (rendering) and TeleopSession
(input); the scene is drawn by Vulkan into images viz owns and reaches
ProjectionLayer.submit() by CUDA pointer, never through host memory.

`--robot` picks which gripper ghost is drawn. This file holds only the machinery;
everything that differs between them -- scene, meshes, mocap bodies, how each
moving part is driven, where it sits on the hand -- is in robots.py.

    VizSession(kXr)  ──get_oxr_handles()──▶  TeleopSession
         │                                        │
         │ vk_device / vk_physical_device         │ controller grip poses
         ▼                                        ▼                      │
    _mujoco_xr.Renderer  ──__cuda_array_interface__──▶  ProjectionLayer  │
         ▲                                                               │
         └──────────────── mjData.mocap_pos/_quat ◀─────────────────────┘

C++ owns mjvScene/mjvOption/mjvCamera; Python owns mjModel/mjData/mj_step, so
everything reading a controller and writing mjData is testable without a GPU.

Frame order is load-bearing: input is sampled before the physics it feeds, on
every frame that will step or draw.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import logging
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
from .robots import DEFAULT_ROBOT, ROBOTS, PartKind, Robot

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

# One hand and no flag: every ghost is right-handed, and the left controller
# draws nothing.
GHOST_HAND = ControllersSource.RIGHT


def _clamp_dt(dt: float) -> float:
    """NaN-safe clamp into [0, MAX_DT_S].

    Spelled as comparisons, not min/max: max(nan, 0) is nan, so the obvious
    form passes NaN through both limits and into mj_step.
    """
    if dt > 0:
        return MAX_DT_S if dt > MAX_DT_S else dt
    return 0.0


def _build_pipeline() -> OutputCombiner:
    """Controllers, plus the shipped jaw retargeter as a graph edge.

    The retargeter is a BaseRetargeter node in the pipeline rather than a
    library call beside it. It is the repository's only proportional
    trigger-to-closedness node; the SO-101 in its name is where it came from, not
    a claim about which gripper reads it, and both ghosts do. The shipped scenes
    have no robot, so the jaw it drives is the operator's own trigger.
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


def _log_startup(robot: Robot, resolution) -> None:
    """One block naming every assumption that is invisible at runtime."""
    try:
        version = importlib.metadata.version("isaacteleop")
    except importlib.metadata.PackageNotFoundError:
        version = "<not installed as a distribution>"
    trans = _mujoco_xr.TRANS_MJ_FROM_XR

    LOG.info("robot:      %s (%s)", robot.key, robot.description)
    LOG.info("scene:      %s", robot.scene)
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
    """The mocap rows the ghost writes, resolved once at startup.

    Mocap indices, not body ids: mocap_pos/mocap_quat are indexed by
    body_mocapid, and a body id there writes into another body's row. `parts` is
    parallel to Robot.parts.
    """

    body: int
    parts: tuple[int, ...]


def _resolve_ghost(model, robot: Robot) -> _GhostChannels:
    """Every ghost mocap row. The robot's scene always declares them."""
    names = (robot.body, *(part.body for part in robot.parts))
    ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n) for n in names]
    missing = [n for n, i in zip(names, ids) if i < 0]
    if missing:
        raise RuntimeError(
            f"mujoco_xr: {robot.scene} declares no `{'` / `'.join(missing)}`; it must "
            f"<include> the {robot.key} gripper fragment."
        )
    rows = [int(model.body_mocapid[i]) for i in ids]
    return _GhostChannels(rows[0], tuple(rows[1:]))


def _update_ghost(data, ghost: _GhostChannels, robot: Robot, result) -> None:
    """Lock the gripper to the GHOST_HAND grip pose; drive its moving parts.

    Keep the validity gate: an untracked controller leaves the grip pose at
    (0, 0, 0), which is the MuJoCo scene origin and a place a legitimate pose
    could put it. Freezing where it was last seen is the honest rendering of
    "tracking lost", so there is no else branch.

    quat_grip_from_ghost right-multiplies because it is fixed in the gripper's
    own frame; left-multiplying swings the ghost around the room as the operator
    turns.
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
    mujoco.mju_mulQuat(q_body, q_grip, robot.quat_grip_from_ghost)
    p_offset = np.empty(3)
    mujoco.mju_rotVecQuat(p_offset, robot.pos_grip_from_ghost, q_grip)
    p_body = p_grip + p_offset

    data.mocap_pos[ghost.body] = p_body
    data.mocap_quat[ghost.body] = q_body

    # Closedness comes through the pipeline output, so the deadzone and clamp
    # are the retargeter's contract rather than this app's.
    closedness = float(result[GRIPPER_COMMAND_KEY][0])
    for part, row in zip(robot.parts, ghost.parts):
        value = part.released + closedness * (part.squeezed - part.released)
        if part.kind is PartKind.HINGE:
            # Rotated ABOUT the pivot, not placed at it: the part's XML rest pose
            # equals the root's, so the pivot lives in exactly one place. Where
            # the origin lands: rotating the ghost frame about the pivot maps 0
            # to (pivot - R . pivot).
            q_local = np.empty(4)
            mujoco.mju_axisAngle2Quat(q_local, part.axis, value)
            swung = np.empty(3)
            mujoco.mju_rotVecQuat(swung, part.pivot, q_local)
            local_offset = part.pivot - swung
            q_part = np.empty(4)
            mujoco.mju_mulQuat(q_part, q_body, q_local)
        else:  # PartKind.SLIDE
            local_offset = part.axis * value
            q_part = q_body

        offset = np.empty(3)
        mujoco.mju_rotVecQuat(offset, local_offset, q_body)
        data.mocap_pos[row] = p_body + offset
        data.mocap_quat[row] = q_part


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


def run(robot: Robot) -> int:
    model = mujoco.MjModel.from_xml_path(str(robot.scene))
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

        _log_startup(robot, resolution)

        # After the startup block, so its line reads as part of the same report.
        ghost = _resolve_ghost(model, robot)
        LOG.info(
            "ghost:      bound to mocap %d (body) / %s (moving); %s, driven by the "
            "controller trigger through SO101GripperRetargeter",
            ghost.body,
            ", ".join(str(row) for row in ghost.parts),
            robot.drive,
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
            _loop(
                viz_session, layer, renderer, model, data, teleop_session, ghost, robot
            )
    finally:
        # The renderer borrows viz_session's device: it must go first.
        if renderer is not None:
            renderer.close()
        viz_session.destroy()
    return 0


def _loop(
    viz_session, layer, renderer, model, data, teleop_session, ghost, robot
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
                _update_ghost(data, ghost, robot, result)

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
    parser.add_argument(
        "--robot",
        choices=sorted(ROBOTS),
        default=DEFAULT_ROBOT,
        help="Which gripper ghost to draw. "
        + "; ".join(f"{k}: {r.description}" for k, r in sorted(ROBOTS.items()))
        + f" (default: {DEFAULT_ROBOT})",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug-level logging.")
    CloudXRLauncher.add_launcher_arguments(parser)
    args = parser.parse_args(argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[mujoco_xr] %(message)s",
    )

    robot = ROBOTS[args.robot]

    # Before launch_context, which starts a runtime process on entry and tears
    # it down on exit: checked here, an unfetched checkout says so plainly
    # instead of landing buried in the runtime's own startup logging. Only the
    # selected robot's meshes are needed, so the other one's absence is not an
    # error.
    missing = robot.missing_meshes()
    if missing:
        raise SystemExit(
            f"mujoco_xr: the {robot.description} meshes are not fetched "
            f"({', '.join(missing)}).\n"
            f"  Run {robot.fetch_script} from the repository root, then reinstall:\n"
            "  uv pip install --reinstall-package isaacteleop-examples-mujoco-xr "
            "./examples/mujoco_xr"
        )

    with CloudXRLauncher.launch_context(args) as launcher:
        if launcher is not None:
            LOG.info("CloudXR runtime started (WSS log: %s)", launcher.wss_log_path)
        try:
            return run(robot)
        except KeyboardInterrupt:
            LOG.info("interrupted")
            return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
