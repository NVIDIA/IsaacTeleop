# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pure helpers from the app that guard against silent-corruption bugs."""

import dataclasses

import pytest

app = pytest.importorskip(
    "isaacteleop_examples.mujoco_xr.app", reason="isaacteleop is not on PYTHONPATH"
)
robots = pytest.importorskip("isaacteleop_examples.mujoco_xr.robots")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.011, 0.011),
        (-1.0, 0.0),  # clock went backwards
        (5.0, app.MAX_DT_S),  # a long stall
    ],
)
def test_clamp_dt(raw, expected):
    assert app._clamp_dt(raw) == expected


def test_clamp_dt_sends_nan_to_zero():
    """The whole reason the clamp uses comparisons.

    ``min(max(nan, 0), 0.1)`` is nan, so NaN passes both limits into mj_step and
    poisons every qpos. ``nan > 0`` is False, so the comparison form sends it to 0.
    """
    assert app._clamp_dt(float("nan")) == 0.0


def test_frame_clock_refuses_the_zeroed_timestamp():
    """Regression: the 50-step physics lurch at every session start.

    ``viz_session.cpp:255-256`` zeroes ``predicted_display_time`` with
    ``should_render`` on every pre-kRunning frame. Sampling that zero makes the
    next real frame compute ``dt = t_now - 0``, clamp to MAX_DT_S, and step 0.1 s
    inside one display frame.
    """

    class _Info:
        predicted_display_time = 0

    assert app._frame_clock(_Info()) is None

    _Info.predicted_display_time = 2_000_000_000  # ns
    assert app._frame_clock(_Info()) == 2.0


class _Fov:
    angle_left = -0.7
    angle_right = 0.7
    angle_up = 0.7
    angle_down = -0.7


def _good_frustum():
    from isaacteleop_examples.mujoco_xr import _mujoco_xr

    return list(
        _mujoco_xr.frustum_from_fov(
            [_Fov.angle_left, _Fov.angle_right, _Fov.angle_up, _Fov.angle_down],
            app.NEAR_Z,
            app.FAR_Z,
        )
    )


def test_assert_frustum_accepts_what_the_renderer_builds():
    """Its rejections mean nothing until it passes on the real thing: float32
    round-tripping alone could make it fire on every frame."""
    app._assert_frustum(_good_frustum(), _Fov(), app.NEAR_Z, app.FAR_Z)


@pytest.mark.parametrize(
    ("index", "broken", "message"),
    [
        # Zero half-width is the one wrong value mjr_render does not complain
        # about: it turns the viewport-aspect fallback on.
        (1, lambda v: 0.0, "degenerate frustum"),
        (5, lambda v: v * 2.0, "clip planes drifted"),
        # The optical axis slid, with nothing else touched.
        (0, lambda v: v + 0.01, "frustum left"),
    ],
)
def test_assert_frustum_rejects(index, broken, message):
    f = _good_frustum()
    f[index] = broken(f[index])
    with pytest.raises(AssertionError, match=message):
        app._assert_frustum(f, _Fov(), app.NEAR_Z, app.FAR_Z)


def test_an_unknown_robot_is_rejected_before_anything_starts():
    """argparse's own gate, and it has to fire before the CloudXR runtime does."""
    with pytest.raises(SystemExit) as exit_info:
        app.main(["mujoco_xr", "--robot", "not-a-robot"])
    assert exit_info.value.code == 2


def test_the_unfetched_message_names_the_SELECTED_robots_script(monkeypatch, tmp_path):
    """One robot's meshes must not satisfy the check for the other's.

    The check runs before CloudXRLauncher.launch_context, so getting it wrong
    means the failure lands buried in a started runtime's own logging instead.
    """
    unfetched = dataclasses.replace(
        robots.SO101,
        key="unfetched",
        assets=tmp_path,
        fetch_script="scripts/fetch-nothing.sh",
    )
    monkeypatch.setattr(app, "ROBOTS", {**app.ROBOTS, "unfetched": unfetched})
    with pytest.raises(SystemExit) as exit_info:
        app.main(["mujoco_xr", "--robot", "unfetched"])
    message = str(exit_info.value)
    assert "fetch-nothing.sh" in message
    assert robots.SO101.meshes[0] in message
