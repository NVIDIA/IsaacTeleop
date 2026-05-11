# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Televiz visualization module.

Lightweight Vulkan compositor for Isaac Teleop. Renders 2D sensor feeds
and 3D content into XR, windowed, or offscreen displays.

Quick start::

    import isaacteleop.viz as viz

    cfg = viz.VizSessionConfig()
    cfg.mode = viz.DisplayMode.kOffscreen
    cfg.window_width = 1024
    cfg.window_height = 1024

    session = viz.VizSession.create(cfg)

    layer_cfg = viz.QuadLayerConfig()
    layer_cfg.name = "cam"
    layer_cfg.resolution = viz.Resolution(1024, 1024)
    layer = session.add_quad_layer(layer_cfg)

    # CuPy / PyTorch / Numba arrays (anything with __cuda_array_interface__):
    layer.submit_cuda_array(cupy_rgba8)

    info = session.render()
    img = session.readback_to_host()      # HostImage with __array_interface__
"""

from ._viz import (
    DisplayMode,
    Fov,
    FrameInfo,
    FrameTimingStats,
    GpuFrameTiming,
    HostImage,
    MemorySpace,
    PixelFormat,
    Pose3D,
    QuadLayer,
    QuadLayerConfig,
    QuadLayerPlacement,
    Rect2D,
    Resolution,
    SessionState,
    VizBuffer,
    VizSession,
    VizSessionConfig,
    bytes_per_pixel,
)

__all__ = [
    "DisplayMode",
    "Fov",
    "FrameInfo",
    "FrameTimingStats",
    "GpuFrameTiming",
    "HostImage",
    "MemorySpace",
    "PixelFormat",
    "Pose3D",
    "QuadLayer",
    "QuadLayerConfig",
    "QuadLayerPlacement",
    "Rect2D",
    "Resolution",
    "SessionState",
    "VizBuffer",
    "VizSession",
    "VizSessionConfig",
    "bytes_per_pixel",
]
