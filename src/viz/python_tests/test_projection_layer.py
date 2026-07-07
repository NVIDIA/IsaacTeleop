# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""End-to-end ProjectionLayer tests via Python bindings.

Covers: config plumbing, add_projection_layer, submit shape validation,
mono+depth round-trip render, stereo + no-depth variants. GPU-gated.

All [gpu] tests share one module-scoped VizSession (and thus one VkContext):
NVIDIA's Linux Vulkan ICD drops out after ~12 instance create/destroy cycles
per process, so each test adds its layer to the shared session and removes it
in teardown rather than spinning up a fresh session.
"""

from __future__ import annotations

import numpy as np
import pytest

import isaacteleop.viz as viz


def _make_session(width=32, height=32):
    cfg = viz.VizSessionConfig()
    cfg.mode = viz.DisplayMode.kOffscreen
    cfg.window_width = width
    cfg.window_height = height
    cfg.clear_color = (0.0, 0.0, 0.0, 1.0)
    return viz.VizSession.create(cfg)


def _gpu_available() -> bool:
    s = None
    try:
        s = _make_session()
    except RuntimeError:
        return False
    finally:
        if s is not None:
            s.destroy()
    return True


pytestmark = pytest.mark.skipif(
    not _gpu_available(), reason="no Vulkan/CUDA-capable GPU"
)


def _need_cupy():
    cp = pytest.importorskip("cupy")
    try:
        if cp.cuda.runtime.getDeviceCount() == 0:
            pytest.skip("no CUDA device")
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("no CUDA device")
    return cp


@pytest.fixture(scope="module")
def session():
    """One offscreen session (one VkContext) shared by every [gpu] test."""
    s = _make_session()
    try:
        yield s
    finally:
        s.destroy()


def test_projection_layer_config_roundtrip():
    cfg = viz.ProjectionLayerConfig()
    cfg.name = "test"
    cfg.view_resolution = viz.Resolution(128, 64)
    cfg.color_format = viz.PixelFormat.kRGBA8
    cfg.depth_format = viz.PixelFormat.kD32F
    cfg.stereo = True

    assert cfg.name == "test"
    assert cfg.view_resolution.width == 128
    assert cfg.view_resolution.height == 64
    assert cfg.depth_format == viz.PixelFormat.kD32F
    assert cfg.stereo is True

    # depth_format can be None
    cfg.depth_format = None
    assert cfg.depth_format is None


def test_add_projection_layer_mono_depth(session):
    cp = _need_cupy()
    layer_cfg = viz.ProjectionLayerConfig()
    layer_cfg.name = "proj"
    layer_cfg.view_resolution = viz.Resolution(32, 32)
    layer = session.add_projection_layer(layer_cfg)
    try:
        assert layer.name == "proj"
        assert layer.is_visible() is True
        assert layer.view_resolution.width == 32
        assert layer.view_resolution.height == 32
        assert layer.color_format == viz.PixelFormat.kRGBA8
        assert layer.depth_format == viz.PixelFormat.kD32F
        assert layer.stereo is False
        assert layer.view_count == 1

        # Submit mono + depth via cupy.
        host_color = np.zeros((32, 32, 4), dtype=np.uint8)
        host_color[..., 2] = 200  # blue channel
        host_color[..., 3] = 255
        host_depth = np.full((32, 32), 0.5, dtype=np.float32)
        layer.submit(cp.asarray(host_color), cp.asarray(host_depth))

        session.render()

        # Predominantly blue at the center; ProjectionLayer covers the
        # whole framebuffer.
        arr = np.asarray(session.readback_to_host())
        r, g, b, _a = arr[16, 16]
        assert b > r and b > g
    finally:
        session.remove_layer(layer)


def test_submit_rejects_missing_depth_on_depth_layer(session):
    cp = _need_cupy()
    layer_cfg = viz.ProjectionLayerConfig()
    layer_cfg.view_resolution = viz.Resolution(32, 32)
    layer = session.add_projection_layer(layer_cfg)
    try:
        color = cp.asarray(np.zeros((32, 32, 4), dtype=np.uint8))
        with pytest.raises(RuntimeError, match="left_depth"):
            layer.submit(color)
    finally:
        session.remove_layer(layer)


def test_submit_rejects_dimension_mismatch(session):
    cp = _need_cupy()
    layer_cfg = viz.ProjectionLayerConfig()
    layer_cfg.view_resolution = viz.Resolution(32, 32)
    layer = session.add_projection_layer(layer_cfg)
    try:
        # Wrong width.
        wrong_color = cp.asarray(np.zeros((32, 16, 4), dtype=np.uint8))
        depth = cp.asarray(np.zeros((32, 32), dtype=np.float32))
        with pytest.raises(RuntimeError, match="resolution"):
            layer.submit(wrong_color, depth)
    finally:
        session.remove_layer(layer)


def test_stereo_round_trip(session):
    cp = _need_cupy()
    layer_cfg = viz.ProjectionLayerConfig()
    layer_cfg.view_resolution = viz.Resolution(32, 32)
    layer_cfg.stereo = True
    layer = session.add_projection_layer(layer_cfg)
    try:
        assert layer.stereo is True
        assert layer.view_count == 2

        host_lc = np.zeros((32, 32, 4), dtype=np.uint8)
        host_lc[..., 0] = 200  # red for LEFT
        host_lc[..., 3] = 255
        host_rc = np.zeros((32, 32, 4), dtype=np.uint8)
        host_rc[..., 1] = 200  # green for RIGHT
        host_rc[..., 3] = 255
        host_d = np.full((32, 32), 0.5, dtype=np.float32)
        lc = cp.asarray(host_lc)
        rc = cp.asarray(host_rc)
        ld = cp.asarray(host_d)
        rd = cp.asarray(host_d)

        # Stereo without right eye → must throw.
        with pytest.raises(RuntimeError, match="right_color"):
            layer.submit(lc, ld)

        # Stereo with both eyes.
        layer.submit(lc, ld, rc, rd)
        session.render()
        # In offscreen (single-view), the LEFT buffer is sampled — so the
        # readback should be predominantly red.
        arr = np.asarray(session.readback_to_host())
        r, g, b, _a = arr[16, 16]
        assert r > g and r > b
    finally:
        session.remove_layer(layer)


def test_no_depth_layer(session):
    cp = _need_cupy()
    layer_cfg = viz.ProjectionLayerConfig()
    layer_cfg.view_resolution = viz.Resolution(32, 32)
    layer_cfg.depth_format = None
    layer = session.add_projection_layer(layer_cfg)
    try:
        assert layer.depth_format is None

        host_color = np.zeros((32, 32, 4), dtype=np.uint8)
        host_color[..., 0] = 255  # red
        host_color[..., 3] = 255
        color = cp.asarray(host_color)

        # Depth-disabled layer must reject any depth buffer.
        depth = cp.asarray(np.zeros((32, 32), dtype=np.float32))
        with pytest.raises(RuntimeError, match="depth-disabled"):
            layer.submit(color, depth)

        layer.submit(color)
        session.render()
        arr = np.asarray(session.readback_to_host())
        r, g, b, _a = arr[16, 16]
        assert r > g and r > b
    finally:
        session.remove_layer(layer)


def test_begin_frame_returns_views_for_renderer(session):
    """``session.begin_frame()`` is the source of truth for poses the
    renderer should render against. In offscreen mode the backend
    returns a single identity-pose ViewInfo."""
    info = session.begin_frame()
    assert len(info.views) >= 1
    session.end_frame()


def test_inloop_submit_pattern(session):
    """The supported pattern: begin_frame → submit (against this frame's
    views) → end_frame, all in one tick. Window/offscreen modes have no
    XR freshness gate, so the layer renders on every frame that submits."""
    cp = _need_cupy()
    layer_cfg = viz.ProjectionLayerConfig()
    layer_cfg.view_resolution = viz.Resolution(32, 32)
    layer = session.add_projection_layer(layer_cfg)
    try:
        host_color = np.zeros((32, 32, 4), dtype=np.uint8)
        host_color[..., 2] = 200  # blue
        host_color[..., 3] = 255
        host_depth = np.full((32, 32), 0.5, dtype=np.float32)

        for _ in range(3):
            info = session.begin_frame()
            assert info.should_render
            # In a real renderer we'd pass info.views to the GPU side; here
            # the buffers are static.
            layer.submit(cp.asarray(host_color), cp.asarray(host_depth))
            session.end_frame()

        # Final readback shows the submitted color.
        arr = np.asarray(session.readback_to_host())
        r, g, b, _a = arr[16, 16]
        assert b > r and b > g
    finally:
        session.remove_layer(layer)
