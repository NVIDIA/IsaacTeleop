# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The whole engage handshake, headless: anchor, align, squeeze, latch, release.

What this covers that the unit tests cannot is the *plumbing* -- the permission leaf out
of ``before_step``, the gate judging the frame outside the graph, and the clutch reading
that answer on the same frame. Every value here is the shipped pipeline's.
"""

import numpy as np
import pytest

app = pytest.importorskip(
    "isaacteleop_examples.robot_viz.app", reason="isaacteleop is not on PYTHONPATH"
)
assets = pytest.importorskip("isaacteleop.viz.robot.assets")

from isaacteleop.retargeting_engine.deviceio_source_nodes import (  # noqa: E402
    ControllersSource,
)
from isaacteleop.retargeting_engine.interface import ComputeContext  # noqa: E402
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (  # noqa: E402
    GraphTime,
)
from isaacteleop.retargeting_engine.interface.tensor_group import (  # noqa: E402
    TensorGroup,
)
from isaacteleop.schema import (  # noqa: E402
    ControllerInputState,
    ControllerPose,
    ControllerSnapshot,
    Point,
    Pose,
    Quaternion,
)
from isaacteleop.viz.robot import (  # noqa: E402
    ClutchPhase,
    ClutchPreview,
    EngageGate,
    InterventionMonitor,
    PreviewArm,
    SceneTwin,
)
from isaacteleop.viz.robot.engage_gate import KEY_ROTATION, KEY_UNREFERENCED  # noqa: E402
from isaacteleop.viz.robot.quaternion import multiply  # noqa: E402
from isaacteleop.viz.robot.so101_ghost import (  # noqa: E402
    grip_quat_from_ghost_body,
    pose_from_ghost_body,
)

# The head the arm anchors against: at the origin, facing -Z, as xyzw.
_HEAD = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
_DT = 1.0 / 72.0
# Comfortably past the gate's 0.1 s dwell at 72 Hz.
_DWELL_FRAMES = 12


class _Rig:
    """One scene, one shipped pipeline, and a controller the test poses by hand."""

    def __init__(self) -> None:
        try:
            scene_path = assets.ensure_so101_scene()
        except OSError as error:
            pytest.skip(f"SO-101 assets unavailable: {error}")
        self.twin = SceneTwin(scene_path)
        self.arm = PreviewArm(self.twin)
        self.pipeline, self.clutch = app._build_pipeline(
            pose_from_ghost_body(*self.arm.gripper_pose_mj())
        )
        # The app's own conjunct name, so a verdict here reads as the shipped one does.
        self.gate = EngageGate(app_conjunct=("limiter", "still catching up"))
        self.preview = ClutchPreview(
            self.twin,
            InterventionMonitor(self.twin),
            self.arm,
            self.clutch,
            self.gate,
        )
        self._spec = ControllersSource(name="controllers").input_spec()
        self._now_ns = 0
        # Where the controller is held for the whole test: exactly the grip the clutch
        # was constructed at, so the commanded pose never jumps and the rate limiter has
        # nothing to catch up on. Anywhere else and its `still catching up` conjunct
        # dominates every verdict, which is a true reading of a badly-posed test.
        self._home_pos = pose_from_ghost_body(*self.arm.gripper_pose_mj())[:3, 3]

    def frame(self, *, head=_HEAD, orientation=None, squeeze: float = 0.0):
        """Drive one whole frame and return the phase after_step settled on."""
        external, events = self.preview.before_step(head)
        # A synthetic clock, because the gate's dwell and the limiter's velocity bound
        # both read graph_time: on the wall clock this loop runs a frame every
        # microsecond, so the dwell would never be served and every motion would look
        # like kilometres per second.
        self._now_ns += int(_DT * 1e9)
        result = self.pipeline.execute_pipeline(
            {"controllers": self._controllers(orientation, squeeze), **external},
            ComputeContext(
                graph_time=GraphTime(
                    sim_time_ns=self._now_ns, real_time_ns=self._now_ns
                ),
                execution_events=events,
            ),
        )
        return self.preview.after_step(result, _DT)

    def frames(self, count: int, **kwargs):
        for _ in range(count):
            phase = self.frame(**kwargs)
        return phase

    def _controllers(self, orientation, squeeze: float):
        """A tracked right controller at the arm's own grip, or at a given orientation."""
        if orientation is None:
            orientation = grip_quat_from_ghost_body(self.arm.gripper_pose_mj()[1])
        quat = Quaternion(*(float(v) for v in orientation))
        pose = ControllerPose(
            Pose(Point(*(float(v) for v in self._home_pos)), quat), True
        )
        snapshot = ControllerSnapshot(
            pose,
            pose,
            ControllerInputState(
                primary_click=False,
                secondary_click=False,
                thumbstick_click=False,
                menu_click=False,
                thumbstick_x=0.0,
                thumbstick_y=0.0,
                squeeze_value=squeeze,
                trigger_value=0.0,
            ),
        )
        inputs = {}
        for name in self._spec:
            group = TensorGroup(self._spec[name])
            group[0] = snapshot
            inputs[name] = group
        return inputs


@pytest.fixture
def rig():
    return _Rig()


def _pitched(quat_xyzw, deg: float) -> np.ndarray:
    """``quat_xyzw`` pitched a further ``deg`` about XR +X, still xyzw.

    Pitch and not yaw, and that is the gate's whole shape here: ``PreviewArm.drive`` turns
    the arm's base onto the wrist's yaw, so the reference carries that yaw too and the
    two cancel. Only pitch and roll are measured against a session constant. A test that
    turned the wrist about +Y would find the gate blind and be reporting the design.
    """
    half = np.radians(deg) / 2.0
    pitch = np.array([np.cos(half), np.sin(half), 0.0, 0.0])
    out = multiply(pitch, np.asarray(quat_xyzw, dtype=float)[[3, 0, 1, 2]])
    return out[[1, 2, 3, 0]]


def test_no_head_pose_means_no_reference_and_no_latch(rig):
    """The un-anchored window: the arm has no pose, so the gate has nothing to judge."""
    rig.frames(_DWELL_FRAMES, head=None, squeeze=1.0)
    assert KEY_UNREFERENCED in rig.preview.verdict.keys
    assert not rig.clutch.is_engaged


def test_an_aligned_wrist_settles_green_and_latches(rig):
    """The happy path, end to end through the shipped graph."""
    rig.frames(_DWELL_FRAMES)
    assert rig.preview.verdict.ok, rig.preview.verdict.blocked

    rig.frame(squeeze=1.0)
    assert rig.clutch.is_engaged
    assert rig.preview.phases.phase is ClutchPhase.ENGAGED


def test_a_turned_wrist_blocks_the_latch(rig):
    """The conjunct the gate exists for: 40 deg off, a squeeze must not latch."""
    turned = _pitched(grip_quat_from_ghost_body(rig.arm.gripper_pose_mj()[1]), 40.0)
    rig.frames(_DWELL_FRAMES, orientation=turned)
    assert KEY_ROTATION in rig.preview.verdict.keys

    rig.frames(_DWELL_FRAMES, orientation=turned, squeeze=1.0)
    assert not rig.clutch.is_engaged


def test_a_denied_latch_stays_owed(rig):
    """Squeezing early costs nothing: the latch fires on the first permitted frame.

    The whole reason permission may be a frame stale. Note the wrist never moves --
    what changes is that the dwell is finally spent.
    """
    turned = _pitched(grip_quat_from_ghost_body(rig.arm.gripper_pose_mj()[1]), 40.0)
    rig.frames(_DWELL_FRAMES, orientation=turned, squeeze=1.0)
    assert not rig.clutch.is_engaged

    rig.frames(_DWELL_FRAMES, squeeze=1.0)
    assert rig.clutch.is_engaged


def test_engagement_survives_a_wrist_that_wanders(rig):
    """Permission gates the LATCH, never the engagement -- revoking it mid-hold is inert."""
    rig.frames(_DWELL_FRAMES)
    rig.frame(squeeze=1.0)
    assert rig.clutch.is_engaged

    turned = _pitched(grip_quat_from_ghost_body(rig.arm.gripper_pose_mj()[1]), 40.0)
    rig.frames(_DWELL_FRAMES, orientation=turned, squeeze=1.0)
    assert rig.clutch.is_engaged


def test_a_release_re_arms_and_the_dwell_debounces_it(rig):
    """Letting go and immediately re-squeezing must serve the dwell again."""
    rig.frames(_DWELL_FRAMES)
    rig.frame(squeeze=1.0)
    assert rig.clutch.is_engaged

    assert rig.frame(squeeze=0.0) is ClutchPhase.DISENGAGED
    assert not rig.clutch.is_engaged
    # One frame later the gate is still spending its dwell, so this cannot re-latch.
    rig.frame(squeeze=1.0)
    assert not rig.clutch.is_engaged

    rig.frames(_DWELL_FRAMES, squeeze=1.0)
    assert rig.clutch.is_engaged
