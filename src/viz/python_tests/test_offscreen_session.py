# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""End-to-end smoke: create a kOffscreen session, add a QuadLayer,
render, readback. Validates the binding plumbing all the way down to
Vulkan + CUDA interop. Skips when no GPU is available.
"""

from __future__ import annotations

import numpy as np
import pytest

import isaacteleop.viz as viz


def _gpu_available() -> bool:
    # Vulkan is the source of truth here. Cheap probe: try to construct
    # an offscreen session; if Vulkan instance / device creation fails,
    # there's no usable GPU on this host. Narrow the catch to RuntimeError
    # (what pybind11 surfaces std::runtime_error as) so binding regressions
    # — AttributeError, TypeError — propagate and fail loudly.
    cfg = viz.VizSessionConfig()
    cfg.mode = viz.DisplayMode.kOffscreen
    cfg.window_width = 64
    cfg.window_height = 64
    s = None
    try:
        s = viz.VizSession.create(cfg)
    except RuntimeError:
        return False
    finally:
        if s is not None:
            s.destroy()
    return True


pytestmark = pytest.mark.skipif(
    not _gpu_available(), reason="no Vulkan/CUDA-capable GPU"
)


def test_offscreen_session_lifecycle():
    cfg = viz.VizSessionConfig()
    cfg.mode = viz.DisplayMode.kOffscreen
    cfg.window_width = 128
    cfg.window_height = 64
    cfg.clear_color = (0.2, 0.4, 0.6, 1.0)

    session = viz.VizSession.create(cfg)
    assert session.get_state() == viz.SessionState.kReady

    info = session.render()
    assert info.frame_index == 0
    assert info.should_render is True

    # No layer added → readback should match the clear color.
    img = session.readback_to_host()
    arr = np.asarray(img)
    assert arr.shape == (64, 128, 4)
    # Clear color is in linear RGB; the framebuffer is SRGB so the
    # readback is back-converted (or not, depending on backend). Don't
    # assert exact pixels — just that the readback isn't all zeros, so
    # we know rendering happened.
    assert arr.any()

    session.destroy()
    assert session.get_state() == viz.SessionState.kDestroyed


def test_quad_layer_round_trip_via_cuda_array_interface():
    try:
        import cupy as cp
    except ImportError:
        pytest.skip("cupy not installed")
    # Treat a CUDARuntimeError (driver missing / wrong libs) as a skip.
    try:
        cnt = cp.cuda.runtime.getDeviceCount()
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("no CUDA device")
    if cnt == 0:
        pytest.skip("no CUDA device")

    cfg = viz.VizSessionConfig()
    cfg.mode = viz.DisplayMode.kOffscreen
    cfg.window_width = 64
    cfg.window_height = 64
    session = viz.VizSession.create(cfg)

    layer_cfg = viz.QuadLayerConfig()
    layer_cfg.name = "cam"
    layer_cfg.resolution = viz.Resolution(32, 32)
    layer = session.add_quad_layer(layer_cfg)
    assert layer.name == "cam"

    # Solid green RGBA8 source. submit consumes
    # __cuda_array_interface__ on the CuPy array.
    #
    # Build host-side first, then H2D once via cp.asarray. Avoiding
    # cp.zeros + setitem keeps us off CuPy's JIT path (the GPU runner
    # ships the driver but not libnvrtc.so).
    host_src = np.zeros((32, 32, 4), dtype=np.uint8)
    host_src[..., 1] = 200  # G
    host_src[..., 3] = 255  # A
    src = cp.asarray(host_src)
    layer.submit(src)

    info = session.render()
    assert info.frame_index == 0

    img = session.readback_to_host()
    arr = np.asarray(img)
    # Center pixel should be predominantly green.
    cx, cy = 32, 32
    r, g, b, _a = arr[cy, cx]
    assert g > r and g > b

    # ── submit validation ──────────────────────────────────
    # Bad inputs built host-side then transferred via cp.asarray so we
    # don't depend on libnvrtc.so being present (cp.zeros / setitem
    # would JIT-compile a fill kernel and the GPU CI runner ships only
    # the driver, not the toolkit).

    # Wrong dtype: layer is RGBA8 (uint8); float32 source must reject.
    bad_dtype = cp.asarray(np.zeros((32, 32, 4), dtype=np.float32))
    with pytest.raises(RuntimeError, match="typestr"):
        layer.submit(bad_dtype)

    # Wrong shape: doesn't match layer resolution.
    bad_shape = cp.asarray(np.zeros((16, 16, 4), dtype=np.uint8))
    with pytest.raises(RuntimeError, match="resolution"):
        layer.submit(bad_shape)

    # Wrong channel count: RGB instead of RGBA.
    bad_channels = cp.asarray(np.zeros((32, 32, 3), dtype=np.uint8))
    with pytest.raises(RuntimeError, match="channel"):
        layer.submit(bad_channels)

    # Wrong rank: 2D for an RGBA layer.
    bad_rank = cp.asarray(np.zeros((32, 32), dtype=np.uint8))
    with pytest.raises(RuntimeError, match="rank"):
        layer.submit(bad_rank)

    session.destroy()


def test_stereo_quad_layer_round_trip():
    """Stereo QuadLayer in offscreen mode renders the LEFT buffer (per
    the documented single-view fallback). Distinct L/R sources confirm
    we're sampling left and not accidentally swapping eyes."""
    cp = pytest.importorskip("cupy")
    try:
        if cp.cuda.runtime.getDeviceCount() == 0:
            pytest.skip("no CUDA device")
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("no CUDA device")

    cfg = viz.VizSessionConfig()
    cfg.mode = viz.DisplayMode.kOffscreen
    cfg.window_width = 64
    cfg.window_height = 64
    session = viz.VizSession.create(cfg)

    layer_cfg = viz.QuadLayerConfig()
    layer_cfg.name = "stereo_cam"
    layer_cfg.resolution = viz.Resolution(32, 32)
    layer_cfg.stereo = True
    layer_cfg.stereo_baseline_mm = 65.0  # roughly human IPD
    layer = session.add_quad_layer(layer_cfg)

    host_left = np.zeros((32, 32, 4), dtype=np.uint8)
    host_left[..., 1] = 200  # G — distinguishable from right
    host_left[..., 3] = 255
    host_right = np.zeros((32, 32, 4), dtype=np.uint8)
    host_right[..., 2] = 200  # B — distinguishable from left
    host_right[..., 3] = 255

    left = cp.asarray(host_left)
    right = cp.asarray(host_right)
    layer.submit(left, right)

    session.render()
    img = session.readback_to_host()
    arr = np.asarray(img)
    cx, cy = 32, 32
    r, g, b, _a = arr[cy, cx]
    # Offscreen / single-view backends draw the LEFT buffer per docs.
    # If we accidentally bound the right descriptor here, this pixel
    # would be blue-dominant instead of green-dominant.
    assert g > r and g > b, (
        f"expected green-dominant (left buffer), got ({r}, {g}, {b})"
    )

    session.destroy()


def test_stereo_invariants():
    """submit's strict mono/stereo contract: one-arg on stereo throws,
    two-arg on mono throws. Validated end-to-end through the binding."""
    cp = pytest.importorskip("cupy")
    try:
        if cp.cuda.runtime.getDeviceCount() == 0:
            pytest.skip("no CUDA device")
    except cp.cuda.runtime.CUDARuntimeError:
        pytest.skip("no CUDA device")

    cfg = viz.VizSessionConfig()
    cfg.mode = viz.DisplayMode.kOffscreen
    cfg.window_width = 64
    cfg.window_height = 64
    session = viz.VizSession.create(cfg)

    mono_cfg = viz.QuadLayerConfig()
    mono_cfg.name = "mono"
    mono_cfg.resolution = viz.Resolution(32, 32)
    # mono_cfg.stereo defaults to False.
    mono_layer = session.add_quad_layer(mono_cfg)

    stereo_cfg = viz.QuadLayerConfig()
    stereo_cfg.name = "stereo"
    stereo_cfg.resolution = viz.Resolution(32, 32)
    stereo_cfg.stereo = True
    stereo_layer = session.add_quad_layer(stereo_cfg)

    blank = cp.asarray(np.zeros((32, 32, 4), dtype=np.uint8))

    # Mono + right buffer → reject.
    with pytest.raises(RuntimeError, match="mono"):
        mono_layer.submit(blank, blank)

    # Stereo + missing right → reject.
    with pytest.raises(RuntimeError, match="stereo"):
        stereo_layer.submit(blank)

    session.destroy()


def test_stereo_invalid_baseline_rejected():
    """Non-finite baseline values must be rejected at ctor time."""
    cfg = viz.VizSessionConfig()
    cfg.mode = viz.DisplayMode.kOffscreen
    cfg.window_width = 64
    cfg.window_height = 64
    session = viz.VizSession.create(cfg)

    layer_cfg = viz.QuadLayerConfig()
    layer_cfg.name = "bad_baseline"
    layer_cfg.resolution = viz.Resolution(32, 32)
    layer_cfg.stereo = True
    layer_cfg.stereo_baseline_mm = float("nan")
    with pytest.raises((RuntimeError, ValueError), match="stereo_baseline_mm"):
        session.add_quad_layer(layer_cfg)

    session.destroy()


def test_quad_layer_visibility_toggle():
    """QuadLayer exposes LayerBase visibility helpers through the Python binding."""
    cfg = viz.VizSessionConfig()
    cfg.mode = viz.DisplayMode.kOffscreen
    cfg.window_width = 64
    cfg.window_height = 64
    session = viz.VizSession.create(cfg)

    layer_cfg = viz.QuadLayerConfig()
    layer_cfg.name = "visibility"
    layer_cfg.resolution = viz.Resolution(32, 32)
    layer = session.add_quad_layer(layer_cfg)

    assert layer.is_visible() is True
    layer.set_visible(False)
    assert layer.is_visible() is False
    layer.set_visible(True)
    assert layer.is_visible() is True

    session.destroy()
