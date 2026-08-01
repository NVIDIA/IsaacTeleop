# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""End-to-end cover for the Vulkan -> CUDA -> ProjectionLayer path.

This is the one test that exercises the genuinely novel machinery in this
example: borrowing VizSession's VkDevice, exporting render-target memory as an
fd, importing it into CUDA, and handing the result to
``ProjectionLayer.submit()`` through ``__cuda_array_interface__``.

It runs in ``kOffscreen``, which needs Vulkan + CUDA but NOT a headset, a
CloudXR runtime or a window system -- so unlike the XR path it is actually
reachable on a developer machine and on a GPU CI runner. It skips cleanly (not
silently: the skip reason names what was missing) everywhere else.

What it does NOT cover, and nothing on a GPU-less machine can: the XR frame
loop, OpenXR session sharing, controller-on-shared-session, and whether the
runtime accepts the depth layer.
"""

import math

import numpy as np
import pytest

RESOLUTION = 256

# NOT re-declared as literals. This module runs the app's own
# _assert_projection against a projection built from these two numbers, so a
# local copy would let app.NEAR_Z change while every assertion here still
# passed -- the test would be checking its own constants, not the shipped ones.
# Same importorskip shape as test_app_helpers.py:10.
app = pytest.importorskip("mujoco_xr.app", reason="isaacteleop is not on PYTHONPATH")
NEAR_Z = app.NEAR_Z
FAR_Z = app.FAR_Z


@pytest.fixture(scope="module")
def viz():
    return pytest.importorskip(
        "isaacteleop.viz", reason="isaacteleop is not on PYTHONPATH"
    )


@pytest.fixture
def gpu_session(viz):
    """A kOffscreen VizSession, or a skip naming why there isn't one."""
    config = viz.VizSessionConfig()
    config.mode = viz.DisplayMode.kOffscreen
    config.app_name = "mujoco_xr_tests"
    config.window_width = RESOLUTION
    config.window_height = RESOLUTION
    config.xr_near_z = NEAR_Z
    config.xr_far_z = FAR_Z
    try:
        session = viz.VizSession.create(config)
    except Exception as exc:  # no Vulkan device, no CUDA device, ...
        pytest.skip(f"no usable Vulkan/CUDA device for an offscreen VizSession: {exc}")
    yield session
    session.destroy()


@pytest.fixture
def scene():
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(app.DEFAULT_SCENE))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return model, data


def _mono_view(resolution):
    """A symmetric fov and a plausible operator pose, as flat float arrays."""
    half_v = math.radians(30.0)
    half_h = math.atan(math.tan(half_v) * resolution.width / resolution.height)
    pitch = math.radians(-25.0)
    pose = [0.0, 1.60, 0.30, math.cos(pitch / 2.0), math.sin(pitch / 2.0), 0.0, 0.0]
    return pose, [-half_h, half_h, half_v, -half_v]


def _make_renderer(session, model, view_count=1):
    from mujoco_xr import _mujoco_xr

    resolution = session.get_recommended_resolution()
    return _mujoco_xr.Renderer(
        vk_physical_device=session.vk_physical_device,
        vk_device=session.vk_device,
        vk_queue_family_index=session.vk_queue_family_index,
        width=resolution.width,
        height=resolution.height,
        view_count=view_count,
        near_z=NEAR_Z,
        far_z=FAR_Z,
        model_address=model._address,
    )


def _add_layer(viz, session):
    resolution = session.get_recommended_resolution()
    config = viz.ProjectionLayerConfig()
    config.name = "mujoco_scene"
    config.view_resolution = resolution
    config.color_format = viz.PixelFormat.kRGBA8
    config.depth_format = viz.PixelFormat.kD32F
    config.stereo = False
    return session.add_projection_layer(config)


def test_cuda_array_interface_matches_the_shape_viz_demands(gpu_session, scene):
    """The exact contract ``cuda_array_to_viz_buffer`` validates.

    A mismatch here is a RuntimeError out of submit(), not corrupted pixels --
    but only because viz checks eagerly. Pin the shape so a change to the
    buffer layout is caught here rather than at submit time on a headset.
    """
    model, _ = scene
    renderer = _make_renderer(gpu_session, model)
    try:
        resolution = gpu_session.get_recommended_resolution()

        color = renderer.color(0).__cuda_array_interface__
        assert color["typestr"] == "|u1"
        assert color["shape"] == (resolution.height, resolution.width, 4)
        assert color["strides"] is None, (
            "tightly packed rows, or viz recomputes the pitch"
        )
        assert color["version"] == 3
        assert color["data"][0] != 0 and color["data"][1] is False

        depth = renderer.depth(0).__cuda_array_interface__
        assert depth["typestr"] == "<f4"
        assert depth["shape"] == (resolution.height, resolution.width)
        assert depth["strides"] is None
        assert depth["data"][0] != color["data"][0], (
            "colour and depth must be distinct allocations"
        )
    finally:
        renderer.close()


def test_render_submit_and_readback_produces_pixels(viz, gpu_session, scene):
    """The whole chain, end to end, with the frame-loop contract respected.

    Also the backstop against the most embarrassing failure mode: a fully
    back-face-culled or mis-projected scene renders BLACK, submits without
    error, and looks exactly like a working pipeline from the outside.
    """
    model, data = scene
    layer = _add_layer(viz, gpu_session)
    renderer = _make_renderer(gpu_session, model)
    try:
        assert renderer.update_scene(model._address, data._address) > 0
        renderer.clear_markers()
        renderer.add_marker(
            pos_mj=[0.0, 0.0, 0.25],
            quat_mj_wxyz=[1.0, 0.0, 0.0, 0.0],
            half_extent=[0.03, 0.03, 0.03],
            rgba=[1.0, 0.0, 1.0, 1.0],
        )
        assert renderer.ngeom < renderer.maxgeom

        pose, fov = _mono_view(gpu_session.get_recommended_resolution())
        gpu_session.begin_frame()
        try:
            renderer.render(pose, fov)
            layer.submit(renderer.color(0), renderer.depth(0))
        finally:
            # end_frame() follows every begin_frame(), including on failure.
            gpu_session.end_frame()

        image = np.asarray(gpu_session.readback_to_host())
        assert image.shape == (
            gpu_session.get_recommended_resolution().height,
            gpu_session.get_recommended_resolution().width,
            4,
        )
        lit = int((image[..., :3].sum(axis=2) > 0).sum())
        assert lit > image.shape[0] * image.shape[1] // 100, (
            f"only {lit} lit pixels -- a black frame submits without error and is routinely "
            "misdiagnosed as a depth bug when it is actually winding or projection"
        )
    finally:
        renderer.close()


def test_markers_are_cleared_not_accumulated(gpu_session, scene):
    """clear_markers() must return to the mjv_updateScene count exactly.

    Getting this wrong grows mjvScene by two geoms per frame until it hits
    maxgeom -- a leak that only manifests after minutes of running.
    """
    model, data = scene
    renderer = _make_renderer(gpu_session, model)
    try:
        base = renderer.update_scene(model._address, data._address)
        for _ in range(5):
            renderer.clear_markers()
            assert renderer.ngeom == base
            renderer.add_marker(
                pos_mj=[0.1, 0.0, 0.1],
                quat_mj_wxyz=[1.0, 0.0, 0.0, 0.0],
                half_extent=[0.02, 0.02, 0.02],
                rgba=[0.0, 1.0, 0.0, 0.5],
            )
            assert renderer.ngeom == base + 1
    finally:
        renderer.close()


def test_renderer_rejects_a_view_count_that_cannot_match_frameinfo(gpu_session, scene):
    model, _ = scene
    from mujoco_xr import _mujoco_xr

    resolution = gpu_session.get_recommended_resolution()
    with pytest.raises(ValueError):
        _mujoco_xr.Renderer(
            vk_physical_device=gpu_session.vk_physical_device,
            vk_device=gpu_session.vk_device,
            vk_queue_family_index=gpu_session.vk_queue_family_index,
            width=resolution.width,
            height=resolution.height,
            view_count=3,
            near_z=NEAR_Z,
            far_z=FAR_Z,
            model_address=model._address,
        )


def test_render_rejects_a_mismatched_view_array_length(gpu_session, scene):
    model, _ = scene
    renderer = _make_renderer(gpu_session, model, view_count=1)
    try:
        # Two views' worth of data into a mono renderer.
        with pytest.raises(ValueError):
            renderer.render([0.0] * 14, [0.1] * 8)
    finally:
        renderer.close()


def test_the_renderers_own_projection_satisfies_the_apps_per_frame_assertion(
    gpu_session, scene
):
    """Runs the SHIPPED assertion, against the SHIPPED clip planes."""
    model, data = scene
    renderer = _make_renderer(gpu_session, model)
    try:
        renderer.update_scene(model._address, data._address)
        pose, fov = _mono_view(gpu_session.get_recommended_resolution())
        gpu_session.begin_frame()
        try:
            renderer.render(pose, fov)
        finally:
            gpu_session.end_frame()
        app._assert_projection(renderer.projection(0), NEAR_Z, FAR_Z)
    finally:
        renderer.close()
