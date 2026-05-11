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
    # there's no usable GPU on this host.
    try:
        cfg = viz.VizSessionConfig()
        cfg.mode = viz.DisplayMode.kOffscreen
        cfg.window_width = 64
        cfg.window_height = 64
        s = viz.VizSession.create(cfg)
        s.destroy()
        return True
    except Exception:
        return False


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

    # Solid green RGBA8 source. submit_cuda_array consumes
    # __cuda_array_interface__ on the CuPy array.
    src = cp.zeros((32, 32, 4), dtype=cp.uint8)
    src[..., 1] = 200  # G
    src[..., 3] = 255  # A
    src = cp.ascontiguousarray(src)
    layer.submit_cuda_array(src)

    info = session.render()
    assert info.frame_index == 0

    img = session.readback_to_host()
    arr = np.asarray(img)
    # Center pixel should be predominantly green.
    cx, cy = 32, 32
    r, g, b, _a = arr[cy, cx]
    assert g > r and g > b

    # ── submit_cuda_array validation ──────────────────────────────────
    # Wrong dtype: layer is RGBA8 (uint8); float32 source must reject.
    bad_dtype = cp.zeros((32, 32, 4), dtype=cp.float32)
    with pytest.raises(RuntimeError, match="typestr"):
        layer.submit_cuda_array(bad_dtype)

    # Wrong shape: doesn't match layer resolution.
    bad_shape = cp.zeros((16, 16, 4), dtype=cp.uint8)
    with pytest.raises(RuntimeError, match="resolution"):
        layer.submit_cuda_array(bad_shape)

    # Wrong channel count: RGB instead of RGBA.
    bad_channels = cp.zeros((32, 32, 3), dtype=cp.uint8)
    with pytest.raises(RuntimeError, match="channel"):
        layer.submit_cuda_array(bad_channels)

    # Wrong rank: 2D for an RGBA layer.
    bad_rank = cp.zeros((32, 32), dtype=cp.uint8)
    with pytest.raises(RuntimeError, match="rank"):
        layer.submit_cuda_array(bad_rank)

    session.destroy()
