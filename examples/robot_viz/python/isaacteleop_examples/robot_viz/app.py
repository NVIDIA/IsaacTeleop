# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A MuJoCo scene drawn into a Televiz XR session.

TeleopSession owns both halves: it creates the OpenXR session the trackers and the
compositor share, and runs the twin's frame loop on its own thread. This module holds no
mjModel and no mjData; it addresses the scene by name and publishes what moved. See
twin.py for that contract and README.md for the rest of the design.

Two cadences, deliberately: the control loop below is paced off the wall clock and the
render thread off the display. The head pose is the one thing that crosses back, read as
"where the operator was" and never as a per-frame signal.
"""

from __future__ import annotations

import argparse
import contextlib
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
from isaacteleop.retargeting_engine.interface import OutputCombiner, ValueInput
from isaacteleop.retargeters.controller_pose import ControllerPoseSource
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
    VIEW_COUNT,
    ClutchPreview,
    EngageGate,
    InterventionMonitor,
    PreviewArm,
    SceneTwin,
    assets,
    frames,
)
from isaacteleop.viz.robot.clutch_preview import (
    COMMANDED_POSE_KEY,
    ENGAGE_PERMITTED_LEAF,
    GHOST_HAND,
    HAND_POSE,
    HAND_POSE_KEY,
    PERMITTED_TYPE,
    log_grip_posture,
)
from isaacteleop.viz.robot.so101_ghost import (
    GHOST_BODY,
    GHOST_JAW_BODY,
    TRIGGER_RELEASED_RAD,
    TRIGGER_SQUEEZED_RAD,
    pose_from_ghost_body,
)

LOG = logging.getLogger("robot_viz")

# The app's only clip planes. TwinRenderConfig hands the same pair to the compositor and to
# the twin's projection, or world-locked geometry swims under head motion -- and only a
# headset shows it.
NEAR_Z = 0.05
FAR_Z = 50.0

# What the harness lets through. Chosen for this demo, not measured against a follower:
# ordinary reaching passes through and a deliberate flick trips the clamp and then the
# reject band. An SO-101's own envelope is lower -- RateLimiterConfig defaults to 0.25 m/s.
_HARNESS = RateLimiterConfig(
    max_linear_velocity=0.5,  # m/s
    max_angular_velocity=2.5,  # rad/s, ~143 deg/s
    reject_linear_velocity=2.0,  # m/s
    reject_angular_velocity=10.0,  # rad/s
)


def _build_pipeline(  # noqa: N803
    home_base_T_ee: np.ndarray,
) -> tuple[OutputCombiner, SO101ClutchRetargeter]:
    """Controllers, the SO-101 jaw and clutch retargeters, the engage gate and the
    harness. ControllerPoseSource is a parallel branch rather than a link in the clutch's
    chain: its Optional output is the app's only tracking-validity oracle.
    """
    controllers = ControllersSource(name="controllers")
    jaw = SO101GripperRetargeter(name="ghost_jaw", input_device=GHOST_HAND).connect(
        {GHOST_HAND: controllers.output(GHOST_HAND)}
    )
    hand = ControllerPoseSource(
        name="hand_pose", pose=HAND_POSE, input_device=GHOST_HAND
    ).connect({GHOST_HAND: controllers.output(GHOST_HAND)})

    clutch = SO101ClutchRetargeter(
        name="ee_pose",
        home_base_T_ee=home_base_T_ee,
        input_device=GHOST_HAND,
        # The same frame the rest of the app drives from. Its orientation delta is
        # invariant to the choice, so this is here for the translation pivot alone.
        controller_pose=HAND_POSE.value,
    )
    # MEASURED_BASE_T_EE_INPUT is left unwired on purpose: it is position-only, so it
    # cannot put the leader on the follower's orientation.
    commanded = clutch.connect(
        {
            GHOST_HAND: controllers.output(GHOST_HAND),
            SO101ClutchRetargeter.ENGAGE_PERMITTED_INPUT: ValueInput(
                ENGAGE_PERMITTED_LEAF, PERMITTED_TYPE
            ).output(ValueInput.VALUE),
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


def _log_startup(scene_path, resolution, backend: str, gl_device: int) -> None:
    """One block naming every assumption that is invisible at runtime."""
    try:
        version = importlib.metadata.version("isaacteleop")
    except importlib.metadata.PackageNotFoundError:
        version = "<not installed as a distribution>"
    trans = frames.TRANS_MJ_FROM_XR

    LOG.info("scene:      %s", scene_path)
    # Several examples ship their own .venv, and picking up the wrong isaacteleop is
    # invisible without this line.
    LOG.info(
        "isaacteleop: %s (version %s)", Path(viz.__file__).resolve().parent, version
    )
    # The version the twin is built with, not one the environment supplies: a scene
    # authored against a newer MuJoCo fails to compile with a parser error naming neither.
    LOG.info("scene backend: MuJoCo %s (private to the twin)", backend)
    LOG.info(
        "views:      %d (stereo)   view resolution: %sx%s",
        VIEW_COUNT,
        resolution.width,
        resolution.height,
    )
    LOG.info(
        "frames:     mj_from_xr translation = (%.3f, %.3f, %.3f) m -- x is operator standoff, "
        "z is a floor datum this session's reference space does not establish "
        "(viz.robot.frames)",
        trans[0],
        trans[1],
        trans[2],
    )


#: `run` returning this means the render thread is still inside the OpenXR runtime.
#: `main` must then leave a self-owned CloudXR runtime running -- see there.
EXIT_TWIN_STUCK = 1


def run() -> int:
    scene_path = assets.ensure_so101_scene()
    twin = SceneTwin(scene_path)
    # Before the Renderer, which uploads geometry once: the follower repoints geom
    # materials and poses its joints here. Not placed until the first head pose.
    arm = PreviewArm(twin)
    monitor = InterventionMonitor(twin)

    # The clutch's home is pushed every non-ENGAGED frame, so this constructor value
    # only has to be well-formed -- nothing can latch before the anchor exists.
    pipeline, clutch = _build_pipeline(pose_from_ghost_body(*arm.gripper_pose_mj()))
    gate = EngageGate(app_conjunct=("limiter", "still catching up"))
    preview = ClutchPreview(twin, monitor, arm, clutch, gate)

    teleop_config = TeleopSessionConfig(
        app_name="RobotViz",
        pipeline=pipeline,
        # Never pass trackers=: TeleopSession discovers them from the graph, and passing
        # them again duplicates the set. It also aggregates their OpenXR extensions for
        # the twin's xrCreateInstance.
        joint_publisher=twin,
        twin_render=TwinRenderConfig(near_z=NEAR_Z, far_z=FAR_Z),
    )
    with TeleopSession(teleop_config) as teleop_session:
        _log_startup(
            scene_path,
            teleop_session.twin_resolution,
            twin.backend_version,
            twin.gl_device_index,
        )
        LOG.info(
            "leader ghost: %s / %s driven as mocap bodies; trigger driven by "
            "SO101GripperRetargeter, %.0f deg released to %.0f deg squeezed",
            GHOST_BODY,
            GHOST_JAW_BODY,
            math.degrees(TRIGGER_RELEASED_RAD),
            math.degrees(TRIGGER_SQUEEZED_RAD),
        )
        arm.log_placement()
        # Before the anchor, and correct there: both angles are reported in the
        # operator's own frame, which the anchor's yaw is exactly what defines.
        log_grip_posture(arm)
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
        LOG.error(
            "the twin's render thread did not exit; leaving the OpenXR session and "
            "the runtime alive. This process will not exit until it completes."
        )
        return EXIT_TWIN_STUCK
    return 0


# The control loop's cadence, wall-clock paced and independent of the display. 30 Hz is
# the rate a real SO-101 loop runs at, so the preview behaves like one.
CONTROL_HZ = 30.0
_CONTROL_DT = 1.0 / CONTROL_HZ


def _loop(teleop_session, preview: ClutchPreview) -> None:
    """Step the graph at :data:`CONTROL_HZ` for as long as the twin is being drawn.

    Nothing here renders. The head pose comes off the session, which publishes whatever the
    render thread last saw; the arm is anchored once, so a one-frame-old pose is the same.
    """
    deadline = time.perf_counter()
    last = deadline
    while teleop_session.twin_rendering:
        if teleop_session.take_twin_recentered():
            LOG.warning(
                "runtime recentered; re-anchoring the preview arm and disengaging for "
                "one frame. Every pose latched in the old reference space is wrong."
            )
            preview.notify_reference_space_changed()
        external_inputs, events = preview.before_step(teleop_session.twin_head_pose)
        result = teleop_session.step(
            external_inputs=external_inputs, execution_events=events
        )
        now = time.perf_counter()
        # Measured, not nominal: the gate's dwell, PhaseMachine's dropout hold and the
        # grip walk all integrate this, and the nominal period turns them into frame counts
        # under overrun.
        preview.after_step(result, now - last)
        last = now
        # Floor the deadline at now, or a stall leaves it in the past and the loop
        # free-runs to catch up at a real dt near zero.
        deadline = max(deadline + _CONTROL_DT, now)
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

    with contextlib.ExitStack() as stack:
        launcher = stack.enter_context(CloudXRLauncher.launch_context(args))
        if launcher.owns_runtime:
            LOG.info("CloudXR runtime started (WSS log: %s)", launcher.wss_log_path)
        try:
            code = run()
        except KeyboardInterrupt:
            LOG.info("interrupted")
            return 0
        if code == EXIT_TWIN_STUCK:
            # Stopping the runtime here would terminate it under a thread still inside
            # its session. Drop the launcher's cleanup instead and let the OS reap: the
            # non-daemon render thread keeps the process alive either way.
            stack.pop_all()
        return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
