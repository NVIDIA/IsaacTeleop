# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``XrTwinSession`` lifecycle and frame-loop invariants, against fakes.

The compositor types are replaced wholesale, so what is under test is this module's own
sequencing. Importing it still needs the built ``_viz``; the fakes replace the runtime,
not the extension.
"""

import math

import pytest

from isaacteleop.viz.robot import session as session_mod
from isaacteleop.viz.robot.session import (
    VIEW_COUNT,
    WAIT_FOR_HEADSET,
    XrTwinSession,
)


_OXR_HANDLES = (1, 2, 3, 4)
_NEAR_Z = 0.05
_FAR_Z = 50.0


class _Resolution:
    width = 1440
    height = 1584


class _Fov:
    angle_left = -0.7
    angle_right = 0.7
    angle_up = 0.7
    angle_down = -0.7


class _Pose:
    position = (0.0, 0.0, 0.0)
    orientation = (1.0, 0.0, 0.0, 0.0)


class _View:
    pose = _Pose()
    fov = _Fov()


class _Info:
    def __init__(self, *, should_render=True, view_count=VIEW_COUNT):
        self.should_render = should_render
        self.views = [_View() for _ in range(view_count)]


class _FakeSession:
    """Records the compositor calls this module is responsible for ordering.

    One shared ``calls`` list across session, layer and twin: the invariants under test
    are orderings BETWEEN them, which separate logs cannot express.
    """

    def __init__(self, frames, calls):
        self._frames = list(frames)
        self.calls = calls
        self.destroyed = False
        self.layer = None
        self.handles = _OXR_HANDLES

    def get_recommended_resolution(self):
        return _Resolution()

    def add_projection_layer(self, config):
        self.layer = _FakeLayer(self.calls)
        return self.layer

    def should_close(self):
        return not self._frames

    def begin_frame(self):
        self.calls.append("begin_frame")
        return self._frames.pop(0)

    def end_frame(self):
        self.calls.append(
            "end_frame" if not self.destroyed else "end_frame_AFTER_DESTROY"
        )

    def destroy(self):
        self.destroyed = True
        self.calls.append("destroy")

    def get_oxr_handles(self):
        return self.handles


class _FakeLayer:
    def __init__(self, calls):
        self._calls = calls
        self.submitted = None

    def submit(self, *images):
        self._calls.append("layer.submit")
        self.submitted = images


class _FakeTwin:
    """A RobotTwin that records its lifecycle and can be told to fail in create()."""

    def __init__(self, calls, *, fail_create=False):
        self._calls = calls
        self._fail_create = fail_create
        self.created_with = None

    def create(self, width, height, view_count, *, near_z, far_z):
        self._calls.append("twin.create")
        self.created_with = (width, height, view_count, near_z, far_z)
        if self._fail_create:
            raise RuntimeError("backend blew up")

    def render(self, poses, fovs):
        self._calls.append("twin.render")

    def color(self, view):
        return f"color{view}"

    def depth(self, view):
        return f"depth{view}"

    def frustum(self, view):
        self._calls.append("twin.frustum")
        # What assert_frustum expects for _Fov at the session's clip planes.
        near, far = _NEAR_Z, _FAR_Z
        left, right = (
            near * math.tan(_Fov.angle_left),
            near * math.tan(_Fov.angle_right),
        )
        bottom, top = near * math.tan(_Fov.angle_down), near * math.tan(_Fov.angle_up)
        return ((left + right) / 2, (right - left) / 2, bottom, top, near, far)

    def destroy(self):
        self._calls.append("twin.destroy")


@pytest.fixture
def patched(monkeypatch):
    """Replace the compositor types so nothing touches Vulkan."""
    holder = {}

    class _Config:
        pass

    def _make(frames, calls):
        holder["session"] = _FakeSession(frames, calls)
        return holder["session"]

    class _FakeVizSession:
        @staticmethod
        def create(config):
            holder["config"] = config
            return holder["pending"]

    monkeypatch.setattr(session_mod, "VizSession", _FakeVizSession)
    monkeypatch.setattr(session_mod, "VizSessionConfig", _Config)
    monkeypatch.setattr(session_mod, "ProjectionLayerConfig", _Config)
    monkeypatch.setattr(session_mod, "DisplayMode", type("D", (), {"kXr": 0}))
    monkeypatch.setattr(
        session_mod, "PixelFormat", type("P", (), {"kRGBA8": 0, "kD32F": 1})
    )
    return holder, _make


def _build(holder, make, frames, *, fail_create=False):
    calls = []
    make(frames, calls)
    holder["pending"] = holder["session"]
    twin = _FakeTwin(calls, fail_create=fail_create)
    xr = XrTwinSession(
        twin,
        app_name="test",
        near_z=_NEAR_Z,
        far_z=_FAR_Z,
        required_extensions=["XR_TEST_extension"],
        layer_name="test_layer",
    )
    return xr, twin, calls


def test_frames_before_entering_raises(patched):
    holder, make = patched
    xr, _, _ = _build(holder, make, [])
    with pytest.raises(RuntimeError, match="Not entered"):
        next(xr.frames())


def test_resolution_before_entering_raises(patched):
    holder, make = patched
    xr, _, _ = _build(holder, make, [])
    with pytest.raises(RuntimeError, match="Not entered"):
        _ = xr.resolution


def test_twin_is_created_with_the_sessions_clip_planes(patched):
    """The clip planes must reach the twin from the session, not a second source."""
    holder, make = patched
    xr, twin, _ = _build(holder, make, [])
    with xr:
        assert twin.created_with == (
            _Resolution.width,
            _Resolution.height,
            VIEW_COUNT,
            _NEAR_Z,
            _FAR_Z,
        )


def test_it_waits_for_a_headset_by_default(patched):
    """viz itself fails fast, which is right for CI and wrong for an app on a rig.

    Regression: NVIDIA/IsaacTeleop@32c9cd680 made oxr::OpenXRSession wait but left the viz
    path alone, so the robot-twin example died with FORM_FACTOR_UNAVAILABLE the moment the headset was
    a second late.
    """
    holder, make = patched
    xr, _, _ = _build(holder, make, [])
    with xr:
        pass
    assert holder["config"].xr_system_wait_seconds == WAIT_FOR_HEADSET


def test_a_caller_can_still_ask_to_fail_fast(patched):
    holder, make = patched
    calls = []
    make([], calls)
    holder["pending"] = holder["session"]
    xr = XrTwinSession(
        _FakeTwin(calls),
        app_name="test",
        near_z=_NEAR_Z,
        far_z=_FAR_Z,
        required_extensions=[],
        layer_name="test_layer",
        system_wait_seconds=0,
    )
    with xr:
        pass
    assert holder["config"].xr_system_wait_seconds == 0


def test_destroy_runs_even_when_create_raised(patched):
    """A twin that built a context before failing must still be torn down."""
    holder, make = patched
    xr, _, calls = _build(holder, make, [], fail_create=True)
    with pytest.raises(RuntimeError, match="backend blew up"):
        with xr:
            pass
    assert calls.index("twin.destroy") < calls.index("destroy")
    assert holder["session"].destroyed


def test_teardown_order_is_twin_then_session(patched):
    """The twin's GPU objects need its context, so it goes first."""
    holder, make = patched
    xr, _, calls = _build(holder, make, [])
    with xr:
        pass
    assert calls.index("twin.destroy") < calls.index("destroy")


def test_end_frame_runs_on_the_not_rendered_path(patched):
    """Skipping end_frame on a pre-kRunning frame wedges the loop."""
    holder, make = patched
    xr, _, calls = _build(holder, make, [_Info(should_render=False), _Info()])
    with xr:
        list(xr.frames())
    assert calls.count("end_frame") == 2


def test_end_frame_runs_when_the_loop_body_raises(patched):
    """And it must land before the session is destroyed."""
    holder, make = patched
    xr, _, calls = _build(holder, make, [_Info()])
    with pytest.raises(ValueError):
        with xr:
            for _frame in xr.frames():
                raise ValueError("caller blew up")
    assert calls.index("end_frame") < calls.index("destroy")


def test_pre_krunning_frames_are_not_yielded(patched):
    holder, make = patched
    xr, _, _ = _build(holder, make, [_Info(should_render=False), _Info()])
    with xr:
        assert len(list(xr.frames())) == 1


def test_a_view_count_this_session_cannot_render_is_refused(patched):
    """A quad-view runtime must fail loudly, not render the wrong two eyes."""
    holder, make = patched
    xr, _, calls = _build(holder, make, [_Info(view_count=4)])
    with xr:
        with pytest.raises(RuntimeError, match="stereo-only"):
            list(xr.frames())
    # The raise happens inside the generator's try, so the frame is still closed out.
    assert calls.count("end_frame") == 1


def test_render_draws_then_submits(patched):
    holder, make = patched
    xr, _, calls = _build(holder, make, [_Info()])
    with xr:
        for frame in xr.frames():
            xr.render(frame)
    assert calls.index("twin.render") < calls.index("layer.submit")


def test_the_frustum_is_checked_on_the_first_rendered_frame_only(patched):
    """Per-frame checking would cost a readback every frame for a fixed convention."""
    holder, make = patched
    xr, _, calls = _build(holder, make, [_Info(), _Info()])
    with xr:
        for frame in xr.frames():
            xr.render(frame)
    assert calls.count("twin.frustum") == VIEW_COUNT
    assert calls.count("twin.render") == 2


def test_render_hands_both_eyes_over_in_order(patched):
    holder, make = patched
    xr, _, _ = _build(holder, make, [_Info()])
    with xr:
        for frame in xr.frames():
            xr.render(frame)
    assert holder["session"].layer.submitted == ("color0", "depth0", "color1", "depth1")


def test_render_after_exit_raises(patched):
    """A frame kept past the session must not reach a destroyed layer."""
    holder, make = patched
    xr, _, _ = _build(holder, make, [_Info()])
    with xr:
        held = next(xr.frames())
    with pytest.raises(RuntimeError, match="Not entered"):
        xr.render(held)


def test_oxr_handles_refuses_a_backend_that_did_not_initialize(patched):
    holder, make = patched
    xr, _, _ = _build(holder, make, [])
    with xr:
        assert xr.oxr_handles() == _OXR_HANDLES
        holder["session"].handles = None
        with pytest.raises(RuntimeError, match="did not initialize"):
            xr.oxr_handles()
