# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The frustum check, against a frustum the renderer actually built.

``assert_frustum`` itself is generic and lives in ``isaacteleop.viz.robot``; its input
here comes from ``viz.robot.frames.frustum_from_fov``, so what is checked is the
assertion against the frustum the renderer really builds. The FrameInfo adapters are
covered in ``src/viz/python_tests/``.
"""

import pytest

app = pytest.importorskip(
    "isaacteleop_examples.robot_viz.app", reason="isaacteleop is not on PYTHONPATH"
)

from isaacteleop.viz.robot import assert_frustum  # noqa: E402


class _Fov:
    angle_left = -0.7
    angle_right = 0.7
    angle_up = 0.7
    angle_down = -0.7


def _good_frustum():
    from isaacteleop.viz.robot import frames

    return list(
        frames.frustum_from_fov(
            [_Fov.angle_left, _Fov.angle_right, _Fov.angle_up, _Fov.angle_down],
            app.NEAR_Z,
            app.FAR_Z,
        )
    )


def test_assert_frustum_accepts_what_the_renderer_builds():
    """Its rejections mean nothing until it passes on the real thing: float32
    round-tripping alone could make it fire on every frame."""
    assert_frustum(_good_frustum(), _Fov(), app.NEAR_Z, app.FAR_Z)


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
        assert_frustum(f, _Fov(), app.NEAR_Z, app.FAR_Z)
