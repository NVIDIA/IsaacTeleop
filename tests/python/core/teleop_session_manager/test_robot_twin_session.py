# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``TeleopSessionConfig.joint_publisher``: the render thread the session owns.

No GPU, no headset and no OpenXR runtime: ``XrTwinSession`` is replaced by a fake that
records the order it was driven in. What is being tested is the ordering and the
teardown contract, which is where the real failures are -- a compositor session
destroyed under a live frame, or trackers torn down while the loop still borrows their
handles.
"""

import threading
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig
from isaacteleop.teleop_session_manager.config import TwinRenderConfig
from isaacteleop.teleop_session_manager.twin_runner import TwinRunner

_HANDLES = (0xA, 0xB, 0xC, 0xD)
# Long enough that a healthy handshake never trips it, short enough that the
# deliberately-wedged tests do not dominate the suite.
_BUDGET_S = 0.5


class _FakeTwin:
    """A ``RobotTwinPublisher`` that counts calls and keeps the latest joints."""

    def __init__(self):
        self.joints = None
        self.created = 0
        self.destroyed = 0
        self.rendered = 0

    def publish(self, joints):
        self.joints = joints

    def create(self, width, height, view_count, *, near_z, far_z):
        self.created += 1
        self.near_z, self.far_z = near_z, far_z

    def render(self, poses, fovs):
        self.rendered += 1

    def color(self, view):
        return None

    def depth(self, view):
        return None

    def frustum(self, view):
        return (0.0, 1.0, -1.0, 1.0, self.near_z, self.far_z)

    def destroy(self):
        self.destroyed += 1


class _FakeInfo:
    """The little of ``viz.FrameInfo`` the runner reads: one view's pose."""

    class _Pose:
        position = (1.0, 2.0, 3.0)
        orientation = (1.0, 0.0, 0.0, 0.0)  # wxyz, as viz reports it

    class _View:
        pose = None

    def __init__(self):
        view = _FakeInfo._View()
        view.pose = _FakeInfo._Pose()
        self.views = [view]


#: What ``head_pose`` makes of ``_FakeInfo``: position, then xyzw.
_HEAD_POSE = [1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0]


class _FakeXrTwinSession:
    """Stands in for the compositor session, recording lifecycle order.

    ``frames()`` yields forever at a trickle, so a runner that fails to stop the loop
    is a hang rather than a pass.
    """

    #: Every instance built during one test, in construction order.
    instances = []

    def __init__(self, twin, **kwargs):
        self.twin = twin
        self.kwargs = kwargs
        self.events = []
        self.entered = threading.Event()
        self.frames_yielded = 0
        #: Set to park the loop inside frames(), modelling a runtime call that does not
        #: come back.
        self.wedge = threading.Event()
        #: Set by the thread once it is actually parked. A test that does not wait on
        #: this races the thread out of its start gate and measures nothing.
        self.wedged = threading.Event()
        #: Set by _fake_viz on the way out. The render thread is deliberately
        #: non-daemon, so a wedge left set would hang the interpreter at exit rather
        #: than fail anything.
        self.release = threading.Event()
        _FakeXrTwinSession.instances.append(self)

    def __enter__(self):
        self.events.append("enter")
        self.twin.create(
            64, 64, 2, near_z=self.kwargs["near_z"], far_z=self.kwargs["far_z"]
        )
        self.entered.set()
        return self

    def __exit__(self, *exc):
        self.twin.destroy()
        self.events.append("exit")
        return False

    def oxr_handles(self):
        return _HANDLES

    @property
    def resolution(self):
        return (64, 64)

    def frames(self):
        while True:
            if self.wedge.is_set():
                self.wedged.set()
                self.release.wait()
                return
            self.frames_yielded += 1
            yield _FakeInfo()
            time.sleep(0.001)

    def render(self, info):
        self.events.append("render")
        self.twin.render([], [])


@contextmanager
def _fake_viz():
    _FakeXrTwinSession.instances = []
    try:
        with patch(
            "isaacteleop.teleop_session_manager.twin_runner.XrTwinSession",
            _FakeXrTwinSession,
        ):
            yield _FakeXrTwinSession.instances
    finally:
        for instance in _FakeXrTwinSession.instances:
            instance.release.set()


def _runner(twin, **kwargs):
    return TwinRunner(
        twin,
        app_name="test",
        required_extensions=["XR_TEST_extension"],
        near_z=0.05,
        far_z=50.0,
        layer_name="twin",
        join_timeout_s=_BUDGET_S,
        **kwargs,
    )


# ---------------------------------------------------------------- TwinRunner


def test_start_creates_the_session_on_the_thread_and_publishes_handles():
    twin = _FakeTwin()
    with _fake_viz():
        runner = _runner(twin)
        runner.start()
        try:
            assert runner.oxr_handles == _HANDLES
            assert twin.created == 1
            assert runner.resolution == (64, 64)
        finally:
            runner.stop_rendering()
            runner.destroy()


def test_nothing_renders_before_begin_rendering():
    """The gate that keeps the first frame from preceding DeviceIOSession."""
    twin = _FakeTwin()
    with _fake_viz() as sessions:
        runner = _runner(twin)
        runner.start()
        try:
            time.sleep(0.05)
            assert sessions[0].frames_yielded == 0
            runner.begin_rendering()
            deadline = time.monotonic() + 2.0
            while twin.rendered == 0 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert twin.rendered > 0
        finally:
            runner.stop_rendering()
            runner.destroy()


def test_the_session_outlives_stop_rendering():
    """Two steps, not one: the loop stops while the handles stay valid."""
    twin = _FakeTwin()
    with _fake_viz() as sessions:
        runner = _runner(twin)
        runner.start()
        runner.begin_rendering()
        time.sleep(0.05)

        assert runner.stop_rendering() is True
        assert not runner.rendering
        assert "exit" not in sessions[0].events, (
            "the compositor session was destroyed before DeviceIOSession could be"
        )

        assert runner.destroy() is True
        assert sessions[0].events[-1] == "exit"
        assert twin.destroyed == 1


def test_the_head_pose_reaches_the_control_thread():
    """The one thing that crosses back: where the operator was on the last frame."""
    twin = _FakeTwin()
    with _fake_viz():
        runner = _runner(twin)
        runner.start()
        try:
            assert runner.head_pose is None
            runner.begin_rendering()
            deadline = time.monotonic() + 2.0
            while runner.head_pose is None and time.monotonic() < deadline:
                time.sleep(0.005)
            assert list(runner.head_pose) == _HEAD_POSE
        finally:
            runner.stop_rendering()
            runner.destroy()


def test_the_twin_is_destroyed_on_the_render_thread():
    """Its GPU objects need its own context, which no other thread holds."""
    twin = _FakeTwin()
    thread_ids = {}
    original_create, original_destroy = twin.create, twin.destroy
    twin.create = lambda *a, **k: (
        thread_ids.__setitem__("create", threading.get_ident()),
        original_create(*a, **k),
    )[1]
    twin.destroy = lambda: (
        thread_ids.__setitem__("destroy", threading.get_ident()),
        original_destroy(),
    )[1]

    with _fake_viz():
        runner = _runner(twin)
        runner.start()
        runner.stop_rendering()
        runner.destroy()

    assert thread_ids["create"] == thread_ids["destroy"] != threading.get_ident()


def test_destroy_is_idempotent_and_safe_before_start():
    with _fake_viz():
        runner = _runner(_FakeTwin())
        assert runner.destroy() is True
        assert runner.destroy() is True


def test_a_failure_creating_the_session_reaches_the_caller():
    class _Boom(_FakeXrTwinSession):
        def __enter__(self):
            raise RuntimeError("no headset")

    with patch("isaacteleop.teleop_session_manager.twin_runner.XrTwinSession", _Boom):
        runner = _runner(_FakeTwin())
        with pytest.raises(RuntimeError, match="no headset"):
            runner.start()
        assert runner.destroy() is True


def test_a_wedged_loop_declines_to_destroy():
    """The whole teardown contract: a stuck thread must leave the session alive."""
    twin = _FakeTwin()
    with _fake_viz() as sessions:
        runner = _runner(twin)
        runner.start()
        sessions[0].wedge.set()
        runner.begin_rendering()
        assert sessions[0].wedged.wait(timeout=5.0)

        assert runner.stop_rendering() is False
        assert runner.destroy() is False
        # Not "it failed to destroy" -- it never tried. Only that thread may.
        assert twin.destroyed == 0
        assert "exit" not in sessions[0].events


# ---------------------------------------------------------------- config


def _pipeline():
    pipeline = MagicMock()
    pipeline.get_leaf_nodes.return_value = []
    return pipeline


def test_joint_publisher_rejects_external_handles():
    with pytest.raises(ValueError, match="mutually exclusive"):
        TeleopSessionConfig(
            app_name="test",
            pipeline=_pipeline(),
            joint_publisher=_FakeTwin(),
            oxr_handles=MagicMock(),
        )


@pytest.mark.parametrize("planes", [(0.0, 1.0), (-1.0, 1.0), (2.0, 1.0), (1.0, 1.0)])
def test_clip_planes_no_projection_could_use_are_refused(planes):
    near_z, far_z = planes
    with pytest.raises(ValueError, match="near_z"):
        TwinRenderConfig(near_z=near_z, far_z=far_z)


# ---------------------------------------------------------------- TeleopSession


@contextmanager
def _session(twin, **config_kwargs):
    """A live TeleopSession with the twin wired in and DeviceIO faked out."""
    deviceio_session = MagicMock()
    deviceio_session.__enter__ = MagicMock(return_value=deviceio_session)
    deviceio_session.__exit__ = MagicMock(return_value=False)

    config = TeleopSessionConfig(
        app_name="test",
        pipeline=_pipeline(),
        joint_publisher=twin,
        twin_render=TwinRenderConfig(join_timeout_s=_BUDGET_S),
        **config_kwargs,
    )
    with (
        _fake_viz() as sessions,
        patch(
            "isaacteleop.deviceio.DeviceIOSession.run", return_value=deviceio_session
        ) as deviceio_run,
        patch("isaacteleop.oxr.OpenXRSession") as oxr_cls,
    ):
        yield TeleopSession(config), sessions, deviceio_run, oxr_cls


def test_the_session_creates_its_own_compositor_session_and_shares_the_handles():
    """The third branch: no internal oxr.OpenXRSession, and DeviceIO gets the twin's."""
    twin = _FakeTwin()
    with _session(twin) as (session, sessions, deviceio_run, oxr_cls):
        with session:
            oxr_cls.assert_not_called()
            handles = deviceio_run.call_args[0][1]
            assert (
                handles.instance,
                handles.session,
                handles.space,
                handles.proc_addr,
            ) == _HANDLES
            assert session.twin_resolution == (64, 64)
            deadline = time.monotonic() + 2.0
            while session.twin_head_pose is None and time.monotonic() < deadline:
                time.sleep(0.005)
            assert list(session.twin_head_pose) == _HEAD_POSE
        assert session.twin_teardown_clean is True
        assert twin.destroyed == 1


def test_the_required_extensions_are_the_trackers_own():
    """One aggregation, used for xrCreateInstance -- not a second, different list."""
    twin = _FakeTwin()
    with _session(twin) as (session, sessions, _deviceio_run, _oxr_cls):
        with patch(
            "isaacteleop.deviceio.DeviceIOSession.get_required_extensions",
            return_value=["XR_EXT_something"],
        ):
            with session:
                assert sessions[0].kwargs["required_extensions"] == ["XR_EXT_something"]


def test_rendering_starts_only_after_deviceio_exists():
    twin = _FakeTwin()
    with _session(twin) as (session, sessions, deviceio_run, _oxr_cls):
        deviceio_run.side_effect = lambda *a, **k: (
            # Checked inside DeviceIOSession.run, which is the moment before the
            # session is allowed to release the frame loop.
            sessions[0].events.append("deviceio"),
            MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False)),
        )[1]
        with session:
            time.sleep(0.05)
        order = [e for e in sessions[0].events if e in ("deviceio", "render")]
        assert order and order[0] == "deviceio"


def test_the_clip_planes_reach_both_the_compositor_and_the_twin():
    twin = _FakeTwin()
    with _session(twin) as (session, sessions, _deviceio_run, _oxr_cls):
        session.config.twin_render = TwinRenderConfig(
            near_z=0.1, far_z=20.0, join_timeout_s=_BUDGET_S
        )
        with session:
            pass
        assert sessions[0].kwargs["near_z"] == 0.1
        assert sessions[0].kwargs["far_z"] == 20.0
        assert (twin.near_z, twin.far_z) == (0.1, 20.0)


def test_a_wedged_render_thread_leaves_the_session_alive_without_raising():
    """`__exit__` reports it rather than raising: the caller decides what to do."""
    twin = _FakeTwin()
    with _session(twin) as (session, sessions, _deviceio_run, _oxr_cls):
        with session:
            sessions[0].wedge.set()
            assert sessions[0].wedged.wait(timeout=5.0)
        assert session.twin_teardown_clean is False
        assert twin.destroyed == 0


def test_without_a_publisher_nothing_changes():
    """The branch must be inert for every existing consumer."""
    deviceio_session = MagicMock()
    deviceio_session.__enter__ = MagicMock(return_value=deviceio_session)
    deviceio_session.__exit__ = MagicMock(return_value=False)
    oxr_session = MagicMock()
    oxr_session.__enter__ = MagicMock(return_value=oxr_session)
    oxr_session.__exit__ = MagicMock(return_value=False)

    config = TeleopSessionConfig(app_name="test", pipeline=_pipeline())
    with (
        patch(
            "isaacteleop.deviceio.DeviceIOSession.run", return_value=deviceio_session
        ),
        patch("isaacteleop.oxr.OpenXRSession", return_value=oxr_session) as oxr_cls,
    ):
        with TeleopSession(config) as session:
            oxr_cls.assert_called_once()
            assert session.twin_resolution is None
            assert session.twin_rendering is False
        assert session.twin_teardown_clean is None


def test_an_object_missing_half_the_protocol_is_refused_at_configuration_time():
    """A background thread dying on its first frame is the failure this replaces."""

    class _RenderOnly(_FakeTwin):
        publish = None

    with pytest.raises(TypeError, match="publish"):
        _runner(_RenderOnly())
