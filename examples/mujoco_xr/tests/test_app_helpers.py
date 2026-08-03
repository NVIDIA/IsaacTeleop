# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pure helpers from the app that guard against silent-corruption bugs."""

import math

import pytest

app = pytest.importorskip(
    "isaacteleop_examples.mujoco_xr.app", reason="isaacteleop is not on PYTHONPATH"
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.011, 0.011),
        (0.0, 0.0),
        (-1.0, 0.0),  # clock went backwards
        (5.0, app.MAX_DT_S),  # a long stall
        (float("inf"), app.MAX_DT_S),
    ],
)
def test_clamp_dt(raw, expected):
    assert app._clamp_dt(raw) == expected


def test_clamp_dt_sends_nan_to_zero():
    """The whole reason the clamp is spelled with comparisons.

    ``min(max(nan, 0), 0.1)`` returns nan -- NaN passes through BOTH limits and
    reaches mj_step, which then poisons every qpos in the model. The comparison
    form sends it to 0 because ``nan > 0`` is False.
    """
    assert app._clamp_dt(float("nan")) == 0.0


def test_frame_clock_refuses_the_zeroed_xr_timestamp():
    """Regression: the 50-step physics lurch at every session start.

    ``viz_session.cpp:255-256`` sets ``should_render = false`` AND
    ``predicted_display_time = 0`` together, on every frame before the session
    reaches kRunning. Sampling that zero as a clock reading makes the next real
    frame compute ``dt = t_now - 0``, which clamps to MAX_DT_S and steps the
    simulation 0.1 s inside a single display frame. _frame_clock must report
    "no sample here" instead, so the caller can skip it.
    """

    class _Info:
        predicted_display_time = 0

    assert app._frame_clock(_Info(), app.viz.DisplayMode.kXr) is None

    _Info.predicted_display_time = 2_000_000_000  # ns
    assert app._frame_clock(_Info(), app.viz.DisplayMode.kXr) == 2.0


def test_frame_clock_falls_back_to_monotonic_outside_xr():
    """predicted_display_time is 0 in window/offscreen for a different reason.

    There is no runtime predicting anything, so 0 there is not a missing
    sample -- and must NOT be treated as one, or those modes never step.
    """

    class _Info:
        predicted_display_time = 0

    for mode in (app.viz.DisplayMode.kWindow, app.viz.DisplayMode.kOffscreen):
        now = app._frame_clock(_Info(), mode)
        assert now is not None and now > 0.0


def test_clock_stall_streak_ignores_the_startup_burst():
    """The watchdog must stay silent through a normal session start.

    ``viz_session.cpp:238`` does not call the backend below kRunning, so a real
    session opens with a long run of ``should_render == False`` frames whose
    ``predicted_display_time`` is 0 -- and nothing throttles them, so hundreds
    go by while the operator is still putting the headset on. If those counted,
    the error would fire at every single startup and the watchdog would be
    deleted by the first person who saw it. This is the test that keeps the
    ``should_render`` gate through the next refactor.
    """
    streak = 0
    for _ in range(500):
        streak = app._clock_stall_streak(streak, 0.0, should_render=False)
    assert streak == 0

    # And a non-rendered frame does not RESET a stall that is already building.
    streak = app._clock_stall_streak(0, 0.0, should_render=True)
    assert app._clock_stall_streak(streak, 0.0, should_render=False) == streak


def test_clock_stall_streak_counts_only_frozen_rendered_frames():
    """A frame the runtime WANTS rendered but that carries no time is the alarm."""
    streak = 0
    for expected in range(1, app.STALL_FRAMES + 1):
        streak = app._clock_stall_streak(streak, 0.0, should_render=True)
        assert streak == expected
    # The caller fires on ``== STALL_FRAMES``, so the threshold has to be
    # reached exactly rather than jumped over.
    assert streak == app.STALL_FRAMES

    # Any real time advance clears it.
    assert app._clock_stall_streak(streak, 0.011, should_render=True) == 0


def test_clock_stall_streak_catches_a_nan_clock():
    """NaN reaches the watchdog as 0, via _clamp_dt -- the reference's own case.

    ``sim_scene.cc:86-97`` exists because a NaN dt takes the else branch of
    every comparison, leaving physics frozen and rendering perfect.
    """
    elapsed = app._clamp_dt(float("nan"))
    assert app._clock_stall_streak(0, elapsed, should_render=True) == 1


def test_near_far_are_a_single_sane_pair():
    assert 0.0 < app.NEAR_Z < app.FAR_Z
    # viz defaults far to 100.0; a tabletop scene does not want that precision
    # spent 50-100 m away.
    assert app.FAR_Z <= 100.0


def test_debug_view_is_a_valid_frustum_not_a_zeroed_one():
    """The non-XR modes must never inherit viz's default-constructed Fov.

    ``window_backend.cpp`` and ``offscreen_backend.cpp`` fill FrameInfo.views
    with one default ViewInfo whose Fov is four zeros; feeding that to the
    projection yields +inf and NaN. The app therefore builds its own, and it
    must be a real frustum.
    """

    class _Res:
        width = 1280
        height = 720

    pose, fov = app._debug_view(_Res())

    assert len(pose) == 7
    assert len(fov) == 4
    angle_left, angle_right, angle_up, angle_down = fov
    assert angle_right > angle_left
    assert angle_up > angle_down
    assert not any(a == 0.0 for a in fov)

    # Unit quaternion, and the eye is above the floor rather than at the XR
    # origin (which under this app's frames convention is inside the table).
    qw, qx, qy, qz = pose[3:]
    assert math.isclose(
        math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz), 1.0, rel_tol=1e-9
    )
    assert pose[1] > 1.0

    # And it survives the shipped per-frame assertion.
    from isaacteleop_examples.mujoco_xr import _mujoco_xr

    app._assert_projection(
        _mujoco_xr.projection_from_fov(fov, app.NEAR_Z, app.FAR_Z),
        app.NEAR_Z,
        app.FAR_Z,
    )


def test_assert_projection_rejects_a_lost_y_flip():
    """The assertion has to actually fire, or it is decoration."""
    from isaacteleop_examples.mujoco_xr import _mujoco_xr

    good = _mujoco_xr.projection_from_fov([-0.7, 0.7, 0.7, -0.7], app.NEAR_Z, app.FAR_Z)
    app._assert_projection(good, app.NEAR_Z, app.FAR_Z)

    flipped = list(good)
    flipped[5] = -flipped[5]  # P[1][1] positive: the angleUp->bottom swap is gone
    with pytest.raises(AssertionError, match=r"P\[1\]\[1\]"):
        app._assert_projection(flipped, app.NEAR_Z, app.FAR_Z)


def test_assert_projection_rejects_reverse_z():
    from isaacteleop_examples.mujoco_xr import _mujoco_xr

    p = list(
        _mujoco_xr.projection_from_fov([-0.7, 0.7, 0.7, -0.7], app.NEAR_Z, app.FAR_Z)
    )
    # Swap the depth endpoints: near -> 1, far -> 0.
    p[10] = -p[10] - 1.0
    p[14] = -p[14]
    with pytest.raises(AssertionError, match="depth encoding"):
        app._assert_projection(p, app.NEAR_Z, app.FAR_Z)


def _eye_pair(x: float, y: float, z: float) -> list[float]:
    """Two eyes 6.5 cm apart on the x axis, midpoint at (x, y, z)."""
    return [x - 0.0325, y, z, 1, 0, 0, 0, x + 0.0325, y, z, 1, 0, 0, 0]


def test_head_travel_probe_flags_a_pinned_position(caplog):
    """The 3DoF case: rotation streams, position does not.

    This is the reading that separates "the scene is mis-placed" from "the head
    is not tracked" -- the two present identically through a headset and have
    disjoint fixes.
    """
    probe = app._HeadTravelProbe()
    with caplog.at_level("WARNING"):
        t = 0.0
        for _ in range(3):
            probe.sample(_eye_pair(0.0, 1.6, 0.0), 2, t)
            t += probe._LOG_PERIOD_S + 0.5
    assert any("ROTATION ONLY" in r.message for r in caplog.records)


def test_head_travel_probe_confirms_real_translation(caplog):
    probe = app._HeadTravelProbe()
    with caplog.at_level("INFO"):
        t = 0.0
        for i in range(3):
            probe.sample(_eye_pair(0.2 * i, 1.6, 0.0), 2, t)
            t += probe._LOG_PERIOD_S + 0.5
    assert any("6DoF confirmed" in r.message for r in caplog.records)
    assert not any(r.levelname == "WARNING" for r in caplog.records)


def test_head_travel_probe_does_not_read_head_roll_as_translation(caplog):
    """Why the eyes are averaged rather than eye 0 being sampled.

    A head ROLL swings either eye through an arc while the head itself stays
    put. Sampling one eye would report that as travel and mask a genuinely
    pinned position -- the exact failure the probe exists to catch.
    """
    probe = app._HeadTravelProbe()
    with caplog.at_level("WARNING"):
        t = 0.0
        for i in range(3):
            d = 0.0325 * (1 if i % 2 else -1)
            probe.sample(
                [-0.0325, 1.6 + d, 0, 1, 0, 0, 0, 0.0325, 1.6 - d, 0, 1, 0, 0, 0], 2, t
            )
            t += probe._LOG_PERIOD_S + 0.5
    assert any("ROTATION ONLY" in r.message for r in caplog.records)


def test_head_travel_probe_ignores_a_short_pose_array():
    """A view-count mismatch must not raise out of the frame loop."""
    probe = app._HeadTravelProbe()
    probe.sample([0.0, 1.6, 0.0, 1, 0, 0, 0], 2, 0.0)  # claims 2 views, supplies 1
    probe.sample([], 0, 0.0)
