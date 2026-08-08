# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pure helpers from the app that guard against silent-corruption bugs."""

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


def test_frame_clock_refuses_the_zeroed_timestamp():
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

    assert app._frame_clock(_Info()) is None

    _Info.predicted_display_time = 2_000_000_000  # ns
    assert app._frame_clock(_Info()) == 2.0


def test_near_far_are_a_single_sane_pair():
    assert 0.0 < app.NEAR_Z < app.FAR_Z
    # viz defaults far to 100.0; an arm's-length scene does not want that
    # precision spent 50-100 m away.
    assert app.FAR_Z <= 100.0


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
