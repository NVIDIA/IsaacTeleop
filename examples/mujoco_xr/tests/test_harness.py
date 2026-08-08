# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The safety harness the ghost renders, and the colour that reports it.

Headless throughout. What no test here can settle is whether an amber gripper
reads as "the harness is holding you back" to someone wearing the headset.
"""

import numpy as np
import pytest

app = pytest.importorskip(
    "isaacteleop_examples.mujoco_xr.app",
    reason="isaacteleop is not on PYTHONPATH",
)
mujoco = pytest.importorskip("mujoco")

from isaacteleop.retargeting_engine.interface import (  # noqa: E402
    ComputeContext,
    ExecutionEvents,
    ExecutionState,
    OptionalTensorGroup,
    TensorGroup,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (  # noqa: E402
    GraphTime,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import (  # noqa: E402
    OptionalTensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (  # noqa: E402
    ControllerInput,
    ControllerInputIndex,
)
from isaacteleop.retargeters.rate_limiter import (  # noqa: E402
    EE_POSE_KEY,
    EePoseRateLimiter,
)

from isaacteleop_examples.mujoco_xr import harness  # noqa: E402

_ID_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)


def _build_io(node):
    """Empty input/output containers for a node; optionals start absent."""

    def make(spec):
        return {
            k: OptionalTensorGroup(v)
            if isinstance(v, OptionalTensorGroupType)
            else TensorGroup(v)
            for k, v in spec.items()
        }

    return make(node.input_spec()), make(node.output_spec())


def _context(time_ns: int = 0, *, reset: bool = False) -> ComputeContext:
    return ComputeContext(
        graph_time=GraphTime(sim_time_ns=time_ns, real_time_ns=time_ns),
        execution_events=ExecutionEvents(
            reset=reset, execution_state=ExecutionState.RUNNING
        ),
    )


def _controller(
    *, pos=(0.0, 0.0, 0.0), quat=_ID_QUAT, valid: bool = True
) -> TensorGroup:
    group = TensorGroup(ControllerInput())
    group[ControllerInputIndex.GRIP_POSITION] = np.asarray(pos, dtype=np.float32)
    group[ControllerInputIndex.GRIP_ORIENTATION] = np.asarray(quat, dtype=np.float32)
    group[ControllerInputIndex.GRIP_IS_VALID] = valid
    return group


def _pose(pos, quat=_ID_QUAT) -> np.ndarray:
    return np.concatenate([np.asarray(pos, float), np.asarray(quat, float)])


# ── GripPoseSource ─────────────────────────────────────────────────────────


def test_grip_pose_source_repacks_the_grip_pose():
    node = harness.GripPoseSource(name="grip", input_device=app.GHOST_HAND)
    inputs, outputs = _build_io(node)
    inputs[app.GHOST_HAND] = _controller(
        pos=(0.1, -0.2, 0.3), quat=(0.0, 0.70710678, 0.0, 0.70710678)
    )

    node._compute_fn(inputs, outputs, _context())

    emitted = np.from_dlpack(outputs[EE_POSE_KEY][0])
    np.testing.assert_allclose(emitted[:3], (0.1, -0.2, 0.3), atol=1e-6)
    # xyzw in, xyzw out. Swapped to wxyz this stays unit-norm and passes every
    # other check while rotating the ghost 90 degrees about the wrong axis.
    np.testing.assert_allclose(
        emitted[3:], (0.0, 0.70710678, 0.0, 0.70710678), atol=1e-6
    )


@pytest.mark.parametrize("absent_input", [False, True])
def test_grip_pose_source_goes_absent_rather_than_emitting_the_origin(absent_input):
    """An untracked grip reads (0, 0, 0) -- the scene origin, a legitimate pose."""
    node = harness.GripPoseSource(name="grip", input_device=app.GHOST_HAND)
    inputs, outputs = _build_io(node)
    if not absent_input:
        inputs[app.GHOST_HAND] = _controller(pos=(0.0, 0.0, 0.0), valid=False)

    node._compute_fn(inputs, outputs, _context())

    assert outputs[EE_POSE_KEY].is_none


# ── Band classification ────────────────────────────────────────────────────


def test_a_still_hand_is_pass_through_not_rejection():
    """The regression that would strobe the ghost red whenever nobody moved.

    A held pose satisfies "emitted equals previous" exactly as a refused frame
    does; only the input comparison separates them.
    """
    still = _pose((0.3, 0.0, 0.0))
    assert harness.classify(still, still, still) is harness.HarnessBand.PASS_THROUGH


def test_pass_through_survives_the_quaternion_double_cover():
    """q and -q are the same rotation; a sign flip must not read as motion."""
    given = _pose((0.0, 0.0, 0.0), (0.0, 0.0, 0.3826834, 0.9238795))
    emitted = _pose((0.0, 0.0, 0.0), (0.0, 0.0, -0.3826834, -0.9238795))
    assert harness.classify(given, emitted, None) is harness.HarnessBand.PASS_THROUGH


def test_partial_motion_is_a_clamp():
    previous = _pose((0.0, 0.0, 0.0))
    emitted = _pose((0.01, 0.0, 0.0))
    given = _pose((0.5, 0.0, 0.0))
    assert harness.classify(given, emitted, previous) is harness.HarnessBand.CLAMPED


def test_no_motion_toward_a_moved_input_is_a_rejection():
    previous = _pose((0.0, 0.0, 0.0))
    given = _pose((0.5, 0.0, 0.0))
    assert harness.classify(given, previous, previous) is harness.HarnessBand.REJECTED


def test_the_first_frame_cannot_be_a_rejection():
    """With no previous pose there is nothing to have been held at."""
    given = _pose((0.5, 0.0, 0.0))
    emitted = _pose((0.01, 0.0, 0.0))
    assert harness.classify(given, emitted, None) is harness.HarnessBand.CLAMPED


# ── The colour the renderer actually reads ─────────────────────────────────


def _scene_model():
    missing = app._missing_leader_assets()
    if missing:
        pytest.skip(
            f"leader meshes not fetched ({', '.join(missing)}); run {app.FETCH_SCRIPT}"
        )
    return mujoco.MjModel.from_xml_path(str(app.DEFAULT_SCENE))


def _rendered_rgba(model, geom_name: str) -> np.ndarray:
    """The mjvGeom rgba the Vulkan draw loop memcpys into its push constants.

    Read off mjvScene, not mjModel: scene_renderer.cpp takes `g->rgba` from the
    mjvGeom, and geom_rgba silently wins over the material when it is set away
    from its default, so an assertion on mat_rgba would prove nothing.
    """
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    option = mujoco.MjvOption()
    mujoco.mjv_defaultOption(option)
    camera = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, camera)
    scene = mujoco.MjvScene(model, 20000)
    mujoco.mjv_updateScene(
        model, data, option, None, camera, mujoco.mjtCatBit.mjCAT_ALL, scene
    )
    geom_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, geom_name)
    for i in range(scene.ngeom):
        g = scene.geoms[i]
        if g.objtype == mujoco.mjtObj.mjOBJ_GEOM and g.objid == geom_id:
            return np.array(g.rgba)
    raise AssertionError(f"{geom_name} is not in the rendered scene")


@pytest.mark.parametrize(
    ("band", "given", "emitted", "previous"),
    [
        (
            harness.HarnessBand.PASS_THROUGH,
            _pose((0.1, 0, 0)),
            _pose((0.1, 0, 0)),
            None,
        ),
        (
            harness.HarnessBand.CLAMPED,
            _pose((0.5, 0, 0)),
            _pose((0.01, 0, 0)),
            _pose((0.0, 0, 0)),
        ),
        (
            harness.HarnessBand.REJECTED,
            _pose((0.5, 0, 0)),
            _pose((0.0, 0, 0)),
            _pose((0.0, 0, 0)),
        ),
    ],
)
def test_the_band_reaches_the_geometry_the_renderer_draws(
    band, given, emitted, previous
):
    model = _scene_model()
    monitor = harness.InterventionMonitor(model)
    monitor._previous = previous
    authored = monitor.pass_through_rgba

    assert monitor.update(model, given, emitted) is band

    for geom in ("leader_ghost_wrist_roll", "leader_ghost_trigger"):
        rgba = _rendered_rgba(model, geom)
        # Opaque in every band. leader_gripper.xml's alpha 1.0 is what keeps
        # draw order free and the ghost out of CloudXR's reprojection buffer;
        # signalling an intervention must not quietly re-take either risk.
        assert rgba[3] == 1.0
        if band is harness.HarnessBand.PASS_THROUGH:
            np.testing.assert_allclose(rgba, authored, atol=1e-6)
        else:
            assert not np.allclose(rgba[:3], authored[:3])


def test_the_bands_are_told_apart_by_colour():
    """Amber and red have to differ, or the two interventions read as one."""
    model = _scene_model()
    monitor = harness.InterventionMonitor(model)

    monitor.update(model, _pose((0.5, 0, 0)), _pose((0.01, 0, 0)))
    clamped = _rendered_rgba(model, "leader_ghost_handle")
    # The clamp above left _previous at (0.01, 0, 0). Rewind it so the next
    # frame emits exactly what it held, which is what makes it a rejection.
    monitor._previous = _pose((0.0, 0, 0))
    monitor.update(model, _pose((0.5, 0, 0)), _pose((0.0, 0, 0)))
    rejected = _rendered_rgba(model, "leader_ghost_handle")

    assert not np.allclose(clamped[:3], rejected[:3])


def test_the_summary_counts_every_governed_frame():
    model = _scene_model()
    monitor = harness.InterventionMonitor(model)
    still = _pose((0.0, 0, 0))
    for _ in range(3):
        monitor.update(model, still, still)
    monitor.update(model, _pose((0.5, 0, 0)), _pose((0.01, 0, 0)))

    assert monitor.counts[harness.HarnessBand.PASS_THROUGH] == 3
    assert monitor.counts[harness.HarnessBand.CLAMPED] == 1
    assert "4 frames" in monitor.summary()


# ── The chain, at the app's own limits ─────────────────────────────────────


def _drive(steps):
    """Run (position, dt) frames through GripPoseSource -> EePoseRateLimiter.

    Yields the band for each frame, using the app's shipped RateLimiterConfig --
    so these tests fail if _HARNESS is retuned past what a hand can reach.
    """
    source = harness.GripPoseSource(name="grip", input_device=app.GHOST_HAND)
    limiter = EePoseRateLimiter(name="harness", config=app._HARNESS)
    src_in, src_out = _build_io(source)
    lim_in, lim_out = _build_io(limiter)
    previous = None
    time_ns = 0

    for position, dt in steps:
        time_ns += int(dt * 1e9)
        context = _context(time_ns)
        src_in[app.GHOST_HAND] = _controller(pos=position)
        source._compute_fn(src_in, src_out, context)
        lim_in[EE_POSE_KEY] = src_out[EE_POSE_KEY]
        limiter._compute_fn(lim_in, lim_out, context)

        given = np.asarray(np.from_dlpack(src_out[EE_POSE_KEY][0]), dtype=float)
        emitted = np.asarray(np.from_dlpack(lim_out[EE_POSE_KEY][0]), dtype=float)
        yield harness.classify(given, emitted, previous)
        previous = emitted


_FRAME_S = 1.0 / 72.0  # a headset frame, which is what the limiter sees


def test_ordinary_reaching_passes_through_untouched():
    """The claim the demo rests on: normal teleop is not governed at all."""
    speed = 0.3  # m/s, an unhurried reach
    steps = [((speed * _FRAME_S * i, 0.0, 0.0), _FRAME_S) for i in range(1, 12)]
    assert all(b is harness.HarnessBand.PASS_THROUGH for b in _drive(steps))


def test_a_fast_sweep_clamps():
    speed = 1.2  # m/s: over the 0.5 m/s clamp, under the 2.0 m/s reject
    steps = [((speed * _FRAME_S * i, 0.0, 0.0), _FRAME_S) for i in range(1, 12)]
    bands = list(_drive(steps))
    # The first frame latches the baseline and cannot be governed.
    assert bands[0] is harness.HarnessBand.PASS_THROUGH
    assert all(b is harness.HarnessBand.CLAMPED for b in bands[1:])


def test_a_teleport_is_refused_rather_than_approached():
    steps = [((0.0, 0.0, 0.0), _FRAME_S), ((3.0, 0.0, 0.0), _FRAME_S)]
    assert list(_drive(steps))[-1] is harness.HarnessBand.REJECTED


# ── The graph the app actually builds ──────────────────────────────────────


def _run_pipeline(*, grip_valid: bool):
    """One frame of the real `_build_pipeline()` graph, driven by a DeviceIO snapshot."""
    from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
    from isaacteleop.schema import (
        ControllerInputState,
        ControllerPose,
        ControllerSnapshot,
        ControllerSnapshotTrackedT,
        Point,
        Pose,
        Quaternion,
    )

    grip = Pose(Point(0.1, 1.2, -0.4), Quaternion(0.0, 0.0, 0.0, 1.0))
    state = ControllerInputState(
        primary_click=False,
        secondary_click=False,
        thumbstick_click=False,
        menu_click=False,
        thumbstick_x=0.0,
        thumbstick_y=0.0,
        squeeze_value=0.0,
        trigger_value=0.0,
    )
    pose = ControllerPose(grip, grip_valid)
    snapshot = ControllerSnapshotTrackedT(ControllerSnapshot(pose, pose, state))

    pipeline = app._build_pipeline()
    spec = ControllersSource(name="controllers").input_spec()
    inputs = {}
    for name in spec:
        group = TensorGroup(spec[name])
        group[0] = snapshot
        inputs[name] = group
    return pipeline.execute_pipeline({"controllers": inputs})


def test_the_pipeline_carries_both_the_governed_pose_and_its_input():
    """The wiring, executed rather than inspected.

    `_build_pipeline` fans the controller out to two consumers and exposes one
    GripPoseSource port under two combiner names -- neither is obviously legal,
    and a connect-time rejection would otherwise surface only on a headset. The
    keys matter as much: `_loop` reads them by name and would silently place
    nothing if either moved.
    """
    out = _run_pipeline(grip_valid=True)

    for key in (
        app.GHOST_HAND,
        app.GRIPPER_COMMAND_KEY,
        app.RAW_POSE_KEY,
        EE_POSE_KEY,
    ):
        assert key in out, f"_loop reads {key!r} and the combiner does not carry it"

    # First frame: the limiter latches and passes through, so the two pose
    # channels agree. They are still distinct ports -- test_a_fast_sweep_clamps
    # is where they come apart.
    given = app._pose(out, app.RAW_POSE_KEY)
    emitted = app._pose(out, EE_POSE_KEY)
    np.testing.assert_allclose(given[:3], (0.1, 1.2, -0.4), atol=1e-6)
    assert harness.classify(given, emitted, None) is harness.HarnessBand.PASS_THROUGH


def test_the_governed_channel_reads_as_absent_before_the_first_valid_grip():
    """Regression: every session started by crashing on its first frame.

    The grip pose is not localizable for the first frames of a session, so
    GripPoseSource goes absent and the limiter has nothing to latch -- and it
    leaves its output tensor UNSET rather than writing. That output is a
    REQUIRED group, whose `is_none` is hardcoded False, so the absence is
    invisible to the check that catches it on RAW_POSE_KEY and `_pose` walked
    straight into "Tensor 'pose' value has not been set".
    """
    out = _run_pipeline(grip_valid=False)

    assert out[app.RAW_POSE_KEY].is_none
    assert not out[EE_POSE_KEY].is_none, (
        "a required group reporting absent would mean the engine changed and "
        "this test no longer covers the case it was written for"
    )
    assert app._pose(out, app.RAW_POSE_KEY) is None
    assert app._pose(out, EE_POSE_KEY) is None
